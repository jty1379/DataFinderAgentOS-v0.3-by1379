"""OpenAI-compatible chat completion service using Tornado's async client."""

from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import urlsplit

from tornado.httpclient import AsyncHTTPClient, HTTPRequest

from config.settings import SETTINGS

LOGGER = logging.getLogger("model")
INTERNAL_REASONING_NAMES = ("think", "analysis", "reasoning")
INTERNAL_REASONING_BLOCK = re.compile(
    r"<(?P<name>think|analysis|reasoning)(?:\s[^>]*)?>.*?</(?P=name)\s*>",
    re.IGNORECASE | re.DOTALL,
)
INTERNAL_REASONING_TAG = re.compile(
    r"</?(?:think|analysis|reasoning)(?:\s[^>]*)?>", re.IGNORECASE
)


class LLMError(ValueError):
    """可展示给管理员的模型服务错误。"""


def _endpoint(base_url: str) -> str:
    base_url = base_url.strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise LLMError("模型接口地址无效")
    if parsed.username or parsed.password:
        raise LLMError("模型接口地址不允许嵌入凭据")
    if base_url.endswith("/chat/completions"):
        return base_url
    return base_url + "/chat/completions"


def _content_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts).strip()
    return ""


def strip_internal_reasoning(text: str) -> str:
    """Remove provider reasoning blocks before content reaches storage or the UI."""
    value = str(text or "")
    previous = None
    while previous != value:
        previous = value
        value = INTERNAL_REASONING_BLOCK.sub("", value)
    value = INTERNAL_REASONING_TAG.sub("", value)
    return value.strip()


def _partial_suffix(value: str, candidates: tuple[str, ...]) -> int:
    lower = value.lower()
    maximum = 0
    for candidate in candidates:
        limit = min(len(candidate) - 1, len(lower))
        for length in range(1, limit + 1):
            if lower.endswith(candidate[:length]):
                maximum = max(maximum, length)
    return maximum


class _ReasoningStreamFilter:
    def __init__(self) -> None:
        self.buffer = ""
        self.active = ""

    def feed(self, piece: str, *, final: bool = False) -> str:
        self.buffer += str(piece or "")
        output: list[str] = []
        open_tokens = tuple(f"<{name}" for name in INTERNAL_REASONING_NAMES)
        while self.buffer:
            lower = self.buffer.lower()
            if self.active:
                close_token = f"</{self.active}>"
                close_index = lower.find(close_token)
                if close_index < 0:
                    if final:
                        self.buffer = ""
                        self.active = ""
                    else:
                        keep = _partial_suffix(self.buffer, (close_token,))
                        self.buffer = self.buffer[-keep:] if keep else ""
                    break
                self.buffer = self.buffer[close_index + len(close_token):]
                self.active = ""
                continue

            openings = [
                (lower.find(token), name)
                for token, name in zip(open_tokens, INTERNAL_REASONING_NAMES, strict=True)
                if lower.find(token) >= 0
            ]
            if openings:
                open_index, name = min(openings, key=lambda item: item[0])
                output.append(self.buffer[:open_index])
                tag_end = self.buffer.find(">", open_index)
                if tag_end < 0:
                    self.buffer = "" if final else self.buffer[open_index:]
                    break
                self.buffer = self.buffer[tag_end + 1:]
                self.active = name
                continue

            if final:
                output.append(self.buffer)
                self.buffer = ""
            else:
                keep = _partial_suffix(self.buffer, open_tokens)
                output.append(self.buffer[:-keep] if keep else self.buffer)
                self.buffer = self.buffer[-keep:] if keep else ""
            break
        return "".join(output)


class LLMService:
    @staticmethod
    async def complete(model: dict, prompt: str) -> dict:
        prompt = prompt.strip()
        if not 1 <= len(prompt) <= 20000:
            raise LLMError("对话内容需为 1—20000 个字符")
        if not model or not model.get("enabled", True):
            raise LLMError("模型不存在或已停用")
        model_name = str(model.get("model_name") or "").strip()
        if not model_name:
            raise LLMError("模型调用标识未配置")
        api_key_env = str(model.get("api_key_env") or "").strip()
        api_key = SETTINGS.secret_from_env(api_key_env)
        if api_key_env and not api_key:
            raise LLMError(f"环境变量 {api_key_env} 未配置")

        messages: list[dict[str, str]] = []
        system_prompt = str(model.get("system_prompt") or "").strip()
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": float(model.get("temperature", 0.7)),
            "top_p": float(model.get("top_p", 1.0)),
            "max_tokens": int(model.get("max_tokens", 2048)),
            "stream": False,
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        chunks = bytearray()

        def receive_chunk(chunk: bytes) -> None:
            if len(chunks) + len(chunk) > 4 * 1024 * 1024:
                raise LLMError("模型服务响应超过 4MB 限制")
            chunks.extend(chunk)

        request = HTTPRequest(
            url=_endpoint(str(model.get("base_url") or "")),
            method="POST",
            headers=headers,
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            connect_timeout=15,
            request_timeout=90,
            follow_redirects=False,
            streaming_callback=receive_chunk,
        )
        started = time.monotonic()
        try:
            response = await AsyncHTTPClient().fetch(request, raise_error=False)
        except LLMError:
            raise
        except Exception as exc:
            LOGGER.exception("model completion request failed", extra={"event": "model_request_failed"})
            raise LLMError("模型服务连接失败或超时") from exc
        latency_ms = max(0, int((time.monotonic() - started) * 1000))
        try:
            data = json.loads(bytes(chunks).decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise LLMError(f"模型服务返回无效 JSON（HTTP {response.code}）") from exc
        if response.code != 200:
            error = data.get("error", {}) if isinstance(data, dict) else {}
            message = error.get("message") if isinstance(error, dict) else ""
            raise LLMError(str(message or f"模型服务返回 HTTP {response.code}")[:500])
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            raise LLMError("模型服务未返回可用回答")
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        text = strip_internal_reasoning(_content_text(message.get("content")))
        if not text:
            text = strip_internal_reasoning(_content_text(first.get("text")))
        if not text:
            raise LLMError("模型回答为空")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        prompt_tokens = max(
            0, int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        )
        completion_tokens = max(
            0,
            int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0),
        )
        total_tokens = max(
            0, int(usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)
        )
        return {
            "text": text,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "latency_ms": latency_ms,
        }

    @staticmethod
    async def complete_stream(model: dict, prompt: str, on_delta) -> dict:
        """Consume an OpenAI-compatible SSE response and expose each text delta."""
        prompt = prompt.strip()
        if not 1 <= len(prompt) <= 20000:
            raise LLMError("对话内容需为 1—20000 个字符")
        if not model or not model.get("enabled", True):
            raise LLMError("模型不存在或已停用")
        model_name = str(model.get("model_name") or "").strip()
        if not model_name:
            raise LLMError("模型调用标识未配置")
        api_key_env = str(model.get("api_key_env") or "").strip()
        api_key = SETTINGS.secret_from_env(api_key_env)
        if api_key_env and not api_key:
            raise LLMError(f"环境变量 {api_key_env} 未配置")
        messages = []
        system_prompt = str(model.get("system_prompt") or "").strip()
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model_name, "messages": messages,
            "temperature": float(model.get("temperature", 0.7)),
            "top_p": float(model.get("top_p", 1.0)),
            "max_tokens": int(model.get("max_tokens", 2048)),
            "stream": True, "stream_options": {"include_usage": True},
        }
        headers = {"Accept": "text/event-stream", "Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        raw = bytearray()
        pending = bytearray()
        text_parts: list[str] = []
        reasoning_filter = _ReasoningStreamFilter()
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        def consume(frame: bytes) -> None:
            lines = []
            for line in frame.replace(b"\r\n", b"\n").split(b"\n"):
                if line.startswith(b"data:"):
                    lines.append(line[5:].strip())
            if not lines:
                return
            payload_bytes = b"".join(lines)
            if payload_bytes == b"[DONE]":
                return
            try:
                event = json.loads(payload_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return
            if isinstance(event.get("error"), dict):
                raise LLMError(str(event["error"].get("message") or "模型流式响应失败")[:500])
            event_usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
            if event_usage:
                usage["prompt_tokens"] = int(event_usage.get("prompt_tokens", event_usage.get("input_tokens", 0)) or 0)
                usage["completion_tokens"] = int(event_usage.get("completion_tokens", event_usage.get("output_tokens", 0)) or 0)
                usage["total_tokens"] = int(event_usage.get("total_tokens", usage["prompt_tokens"] + usage["completion_tokens"]) or 0)
            choices = event.get("choices") if isinstance(event.get("choices"), list) else []
            if choices and isinstance(choices[0], dict):
                delta = choices[0].get("delta") if isinstance(choices[0].get("delta"), dict) else {}
                raw_content = delta.get("content")
                piece = raw_content if isinstance(raw_content, str) else _content_text(raw_content)
                if piece:
                    safe_piece = reasoning_filter.feed(piece)
                    if not safe_piece:
                        return
                    text_parts.append(safe_piece)
                    if on_delta:
                        on_delta(safe_piece)

        def receive_chunk(chunk: bytes) -> None:
            if len(raw) + len(chunk) > 4 * 1024 * 1024:
                raise LLMError("模型服务响应超过 4MB 限制")
            raw.extend(chunk)
            pending.extend(chunk)
            while b"\n\n" in pending or b"\r\n\r\n" in pending:
                normalized = pending.replace(b"\r\n", b"\n")
                frame, rest = normalized.split(b"\n\n", 1)
                pending.clear()
                pending.extend(rest)
                consume(frame)

        request = HTTPRequest(
            url=_endpoint(str(model.get("base_url") or "")), method="POST",
            headers=headers, body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            connect_timeout=15, request_timeout=90, follow_redirects=False,
            streaming_callback=receive_chunk,
        )
        started = time.monotonic()
        try:
            response = await AsyncHTTPClient().fetch(request, raise_error=False)
        except LLMError:
            raise
        except Exception as exc:
            LOGGER.exception("model stream request failed", extra={"event": "model_stream_failed"})
            raise LLMError("模型服务连接失败或超时") from exc
        latency_ms = max(0, int((time.monotonic() - started) * 1000))
        if pending:
            consume(bytes(pending))
        tail = reasoning_filter.feed("", final=True)
        if tail:
            text_parts.append(tail)
            if on_delta:
                on_delta(tail)
        if response.code != 200:
            raise LLMError(f"模型服务返回 HTTP {response.code}")
        text = "".join(text_parts).strip()
        if not text:
            try:
                fallback = json.loads(bytes(raw).decode("utf-8"))
                choices = fallback.get("choices") or []
                message = choices[0].get("message", {}) if choices else {}
                text = strip_internal_reasoning(_content_text(message.get("content")))
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, IndexError):
                text = ""
        if not text:
            raise LLMError("模型未返回可用的流式回答")
        return {"text": text, **usage, "latency_ms": latency_ms}
