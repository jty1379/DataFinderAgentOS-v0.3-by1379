"""Asynchronous, database-backed OpenAI-compatible multimodal tasks."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlsplit

import tornado.ioloop
from tornado.httpclient import AsyncHTTPClient, HTTPRequest

from app.models.multimodal import MultimodalConfigRepository, MultimodalTaskRepository
from app.services.collector import _validate_public_url
from config.settings import BASE_DIR, SETTINGS

LOGGER = logging.getLogger("multimodal")
MAX_RESPONSE_BYTES = 12 * 1024 * 1024


class MultimodalError(ValueError):
    """A configuration or provider error safe to display to users."""


class MultimodalService:
    @staticmethod
    def submit(
        task_type: str,
        prompt: str,
        *,
        user_id: int | None = None,
        style: str = "default",
        image_size: str = "",
        duration: int = 5,
    ) -> dict:
        prompt = str(prompt or "").strip()
        if not 1 <= len(prompt) <= 4000:
            raise MultimodalError("提示词需为 1—4000 个字符")
        config = MultimodalConfigRepository.get_config()
        if task_type == "image":
            size = image_size or str(config.get("default_image_size") or "1024x1024")
            if size not in {"512x512", "1024x1024", "1024x1536", "1536x1024"}:
                raise MultimodalError("图片尺寸不受支持")
            parameters = {"style": str(style or "default")[:50], "image_size": size}
        elif task_type == "video":
            duration = min(60, max(1, int(duration or 5)))
            parameters = {"duration": duration}
        else:
            raise MultimodalError("不支持的多模态任务类型")
        task = MultimodalTaskRepository.create(task_type, prompt, parameters, user_id)
        MultimodalService.schedule(task["task_id"])
        return task

    @staticmethod
    def schedule(task_id: str) -> None:
        tornado.ioloop.IOLoop.current().spawn_callback(MultimodalService.run, task_id)

    @staticmethod
    async def run(task_id: str) -> dict | None:
        task = MultimodalTaskRepository.get(task_id)
        if not task or task["status"] != "pending":
            return task
        config = MultimodalConfigRepository.get_config()
        provider = str(config.get("provider") or "openai_compatible")
        started = time.monotonic()
        if not MultimodalTaskRepository.mark_running(task_id, provider):
            return MultimodalTaskRepository.get(task_id)
        try:
            if not config.get("enabled"):
                raise MultimodalError("多模态服务未启用")
            if task["task_type"] == "video":
                raise MultimodalError("生视频服务未配置/不可用，系统不会返回模拟视频地址")
            resource_url, provider_task_id, provider_result = await MultimodalService._image(
                task, config
            )
            MultimodalTaskRepository.complete(
                task_id,
                resource_url=resource_url,
                provider_task_id=provider_task_id,
                result={"image_url": resource_url, "provider": provider, **provider_result},
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except MultimodalError as exc:
            MultimodalTaskRepository.fail(
                task_id, str(exc), int((time.monotonic() - started) * 1000)
            )
        except Exception:
            LOGGER.exception(
                "multimodal task failed",
                extra={"task_id": task_id, "event": "multimodal_task_failed"},
            )
            MultimodalTaskRepository.fail(
                task_id,
                "多模态服务调用异常，请检查服务配置与运行日志",
                int((time.monotonic() - started) * 1000),
            )
        return MultimodalTaskRepository.get(task_id)

    @staticmethod
    def _endpoint(base_url: str, provider: str = "openai_compatible") -> str:
        base_url = str(base_url or "").strip().rstrip("/")
        if not base_url:
            raise MultimodalError("请先配置多模态服务地址")
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise MultimodalError("多模态服务地址必须使用 HTTPS")
        if provider == "minimax":
            return base_url if base_url.endswith("/image_generation") else base_url + "/image_generation"
        return (
            base_url
            if base_url.endswith("/images/generations")
            else base_url + "/images/generations"
        )

    @staticmethod
    async def _image(task: dict, config: dict) -> tuple[str, str, dict]:
        provider = str(config.get("provider") or "openai_compatible")
        endpoint = MultimodalService._endpoint(config.get("base_url") or "", provider)
        await _validate_public_url(endpoint)
        api_key = SETTINGS.secret_from_env(str(config.get("api_key_env") or ""))
        if not api_key:
            raise MultimodalError("多模态 API Key 环境变量未配置或没有值")
        model = str(config.get("image_model") or "").strip()
        if not model:
            raise MultimodalError("请配置图片模型名称")
        parameters = task.get("parameters") or {}
        prompt = task["prompt"]
        style = str(parameters.get("style") or "default")
        if style != "default":
            prompt = f"风格要求：{style}\n{prompt}"
        image_size = parameters.get("image_size") or "1024x1024"
        if provider == "minimax":
            aspect_ratios = {
                "512x512": "1:1",
                "1024x1024": "1:1",
                "1024x1536": "2:3",
                "1536x1024": "3:2",
            }
            payload = {
                "model": model,
                "prompt": prompt,
                "aspect_ratio": aspect_ratios.get(image_size, "1:1"),
                "response_format": "url",
                "n": 1,
                "prompt_optimizer": True,
            }
        else:
            payload = {"model": model, "prompt": prompt, "n": 1, "size": image_size}
        chunks = bytearray()

        def receive(chunk: bytes) -> None:
            if len(chunks) + len(chunk) > MAX_RESPONSE_BYTES:
                raise MultimodalError("多模态服务响应超过 12MB 限制")
            chunks.extend(chunk)

        try:
            response = await AsyncHTTPClient().fetch(
                HTTPRequest(
                    endpoint,
                    method="POST",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    connect_timeout=15,
                    request_timeout=120,
                    follow_redirects=False,
                    streaming_callback=receive,
                ),
                raise_error=False,
            )
        except MultimodalError:
            raise
        except Exception as exc:
            raise MultimodalError("多模态服务连接失败或超时") from exc
        raw = bytes(chunks)
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise MultimodalError("多模态服务未返回有效 JSON") from exc
        if response.code < 200 or response.code >= 300:
            message = data.get("error", {}).get("message") if isinstance(data, dict) else ""
            raise MultimodalError(message or f"多模态服务返回 HTTP {response.code}")
        if provider == "minimax" and isinstance(data, dict):
            base_resp = data.get("base_resp") if isinstance(data.get("base_resp"), dict) else {}
            if int(base_resp.get("status_code", 0) or 0) != 0:
                raise MultimodalError(str(base_resp.get("status_msg") or "MiniMax 图片生成失败")[:500])
            result_data = data.get("data") if isinstance(data.get("data"), dict) else {}
            urls = result_data.get("image_urls") if isinstance(result_data.get("image_urls"), list) else []
            encoded_items = result_data.get("image_base64") if isinstance(result_data.get("image_base64"), list) else []
            entries = ([{"url": urls[0]}] if urls else
                       [{"b64_json": encoded_items[0]}] if encoded_items else [])
        else:
            entries = data.get("data") if isinstance(data, dict) else None
        if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
            raise MultimodalError("多模态服务响应缺少图片结果")
        item = entries[0]
        resource_url = str(item.get("url") or "").strip()
        if resource_url:
            parsed = urlsplit(resource_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise MultimodalError("多模态服务返回了无效图片地址")
        else:
            encoded = str(item.get("b64_json") or "")
            if not encoded:
                raise MultimodalError("多模态服务响应缺少图片 URL 或图片数据")
            try:
                image_data = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise MultimodalError("多模态服务返回的图片数据无效") from exc
            if not image_data or len(image_data) > 10 * 1024 * 1024:
                raise MultimodalError("生成图片为空或超过 10MB 限制")
            path = MultimodalService.asset_path(task["task_id"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(image_data)
            resource_url = f"/multimodal/assets/{task['task_id']}.png"
        provider_task_id = str(data.get("id") or data.get("created") or "")[:200]
        return resource_url, provider_task_id, {"revised_prompt": item.get("revised_prompt", "")}

    @staticmethod
    def asset_path(task_id: str) -> Path:
        return BASE_DIR / "data" / "multimodal" / f"{task_id}.png"

    @staticmethod
    def get_task_status(task_id: str, user_id: int | None = None) -> dict | None:
        return MultimodalTaskRepository.get(task_id, user_id)

    @staticmethod
    def list_tasks(task_type: str = "", limit: int = 50) -> list[dict]:
        return MultimodalTaskRepository.list(task_type, limit)

    @staticmethod
    def delete_task(task_id: str) -> bool:
        deleted = MultimodalTaskRepository.delete(task_id)
        path = MultimodalService.asset_path(task_id)
        if path.exists():
            path.unlink()
        return deleted
