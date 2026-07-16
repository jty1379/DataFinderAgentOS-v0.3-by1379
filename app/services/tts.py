"""语音合成服务。"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import time

from tornado.httpclient import AsyncHTTPClient, HTTPRequest

from config.settings import SETTINGS

LOGGER = logging.getLogger("tts")


class TTSConfigurationError(ValueError):
    """TTS 配置错误。"""


class TTSServiceError(ValueError):
    """TTS 服务调用错误。"""


CHUNK_SIZE = 500
MAX_TEXT_LENGTH = 5000


def _text_chunks(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= CHUNK_SIZE:
        return [text]
    sentences = re.split(r"([。！？；\n\r]+)", text)
    chunks = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) <= CHUNK_SIZE:
            current += sentence
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks[:20]


def _cache_path(text_hash: str) -> str:
    cache_dir = SETTINGS.data_dir / "tts_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return str(cache_dir / f"{text_hash}.mp3")


def _text_hash(text: str, voice: str) -> str:
    return hashlib.md5(f"{voice}:{text}".encode("utf-8")).hexdigest()


def _read_file(path: str) -> bytes | None:
    try:
        with open(path, "rb") as f:
            return f.read()
    except (IOError, OSError):
        return None


def _write_file(path: str, data: bytes) -> bool:
    try:
        with open(path, "wb") as f:
            f.write(data)
        return True
    except (IOError, OSError):
        return False


class TTSService:
    @staticmethod
    def get_config() -> dict:
        config = SETTINGS.config.get("tts", {})
        return {
            "enabled": bool(config.get("enabled", False)),
            "provider": str(config.get("provider", "volcengine")).lower(),
            "default_voice": str(config.get("default_voice", "zh_female")),
            "api_key_env": str(config.get("api_key_env", "")),
            "api_secret_env": str(config.get("api_secret_env", "")),
            "base_url": str(config.get("base_url", "")),
            "rate": int(config.get("rate", 0)),
            "volume": int(config.get("volume", 0)),
            "pitch": int(config.get("pitch", 0)),
        }

    @staticmethod
    def is_enabled() -> bool:
        return TTSService.get_config().get("enabled", False)

    @staticmethod
    async def synthesize(text: str, voice: str = "", user_id: int | None = None) -> dict:
        config = TTSService.get_config()
        if not config.get("enabled"):
            raise TTSServiceError("语音合成服务未启用")
        text = text.strip()
        if not 1 <= len(text) <= MAX_TEXT_LENGTH:
            raise TTSServiceError(f"文本长度需为 1—{MAX_TEXT_LENGTH} 个字符")
        voice = voice or config.get("default_voice", "zh_female")
        text_hash = _text_hash(text, voice)
        cache_file = _cache_path(text_hash)
        cached_data = _read_file(cache_file)
        if cached_data:
            return {
                "ok": True,
                "audio_url": f"/tts/audio/{text_hash}.mp3",
                "from_cache": True,
                "length": len(cached_data),
                "voice": voice,
            }
        chunks = _text_chunks(text)
        if not chunks:
            raise TTSServiceError("文本内容为空")
        audio_parts = []
        for chunk in chunks:
            part = await TTSService._synthesize_chunk(chunk, voice, config)
            audio_parts.append(part)
        combined = b"".join(audio_parts)
        _write_file(cache_file, combined)
        return {
            "ok": True,
            "audio_url": f"/tts/audio/{text_hash}.mp3",
            "from_cache": False,
            "length": len(combined),
            "voice": voice,
            "chunks": len(chunks),
        }

    @staticmethod
    async def _synthesize_chunk(text: str, voice: str, config: dict) -> bytes:
        provider = config.get("provider", "volcengine")
        if provider == "volcengine":
            return await TTSService._volcengine_tts(text, voice, config)
        elif provider == "aliyun":
            return await TTSService._aliyun_tts(text, voice, config)
        elif provider == "local":
            return TTSService._local_tts(text, voice)
        else:
            raise TTSConfigurationError(f"不支持的 TTS 提供商: {provider}")

    @staticmethod
    async def _volcengine_tts(text: str, voice: str, config: dict) -> bytes:
        api_key = SETTINGS.secret_from_env(str(config.get("api_key_env", "")))
        api_secret = SETTINGS.secret_from_env(str(config.get("api_secret_env", "")))
        if not api_key or not api_secret:
            raise TTSConfigurationError("火山引擎 TTS API Key 或 Secret 未配置")
        import hmac
        import datetime
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        canonical_uri = "/api/text/speech"
        query_string = f"Action=GetTts&Version=2023-04-01"
        string_to_sign = f"POST\n{canonical_uri}\n{query_string}"
        signature = hmac.new(
            api_secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Timestamp": timestamp,
            "Authorization": f"HMAC-SHA256 Credential={api_key},SignedHeaders=content-type;x-timestamp,Signature={signature}",
        }
        payload = {
            "Text": text,
            "Voice": voice,
            "Language": "zh",
            "Rate": config.get("rate", 0),
            "Volume": config.get("volume", 0),
            "Pitch": config.get("pitch", 0),
            "Format": "mp3",
        }
        base_url = str(config.get("base_url", "https://openspeech.bytedance.net"))
        url = f"{base_url.rstrip('/')}{canonical_uri}?{query_string}"
        chunks = bytearray()

        def receive(chunk: bytes) -> None:
            if len(chunks) + len(chunk) > 2 * 1024 * 1024:
                raise TTSServiceError("TTS 响应超过 2MB 限制")
            chunks.extend(chunk)

        request = HTTPRequest(
            url=url,
            method="POST",
            headers=headers,
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            connect_timeout=10,
            request_timeout=30,
            follow_redirects=False,
            streaming_callback=receive,
        )
        started = time.monotonic()
        try:
            response = await AsyncHTTPClient().fetch(request, raise_error=False)
        except Exception as exc:
            LOGGER.exception("volcengine tts request failed", extra={"event": "tts_volcengine_failed"})
            raise TTSServiceError("语音合成服务连接失败") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.code != 200:
            try:
                error_data = json.loads(bytes(chunks).decode("utf-8", errors="replace"))
                message = error_data.get("message") or error_data.get("Error", {}).get("Message", "")
            except json.JSONDecodeError:
                message = ""
            raise TTSServiceError(message or f"TTS 服务返回 HTTP {response.code}")
        content_type = response.headers.get("Content-Type", "")
        if content_type.startswith("application/json"):
            try:
                error_data = json.loads(bytes(chunks).decode("utf-8", errors="replace"))
                message = error_data.get("message") or error_data.get("Error", {}).get("Message", "")
            except json.JSONDecodeError:
                message = ""
            raise TTSServiceError(message or "TTS 服务返回错误")
        return bytes(chunks)

    @staticmethod
    async def _aliyun_tts(text: str, voice: str, config: dict) -> bytes:
        api_key = SETTINGS.secret_from_env(str(config.get("api_key_env", "")))
        api_secret = SETTINGS.secret_from_env(str(config.get("api_secret_env", "")))
        if not api_key or not api_secret:
            raise TTSConfigurationError("阿里云 TTS API Key 或 Secret 未配置")
        import hmac
        import datetime
        import urllib.parse
        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        headers = {
            "Content-Type": "application/json",
            "Date": timestamp,
            "Accept": "audio/mpeg",
        }
        payload = {
            "Text": text,
            "Voice": voice,
            "Format": "mp3",
            "SampleRate": "16000",
            "SpeechRate": config.get("rate", 0),
            "Volume": config.get("volume", 0),
            "PitchRate": config.get("pitch", 0),
        }
        base_url = str(config.get("base_url", "https://nls-gateway.cn-shanghai.aliyuncs.com"))
        url = f"{base_url.rstrip('/')}/stream/v1/tts"
        string_to_sign = f"POST\n/application/json\n{timestamp}\n/nls-gateway.cn-shanghai.aliyuncs.com/stream/v1/tts"
        signature = base64.b64encode(
            hmac.new(api_secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).digest()
        ).decode("utf-8")
        authorization = f"Dataplus {api_key}:{signature}"
        headers["Authorization"] = authorization
        chunks = bytearray()

        def receive(chunk: bytes) -> None:
            if len(chunks) + len(chunk) > 2 * 1024 * 1024:
                raise TTSServiceError("TTS 响应超过 2MB 限制")
            chunks.extend(chunk)

        request = HTTPRequest(
            url=url,
            method="POST",
            headers=headers,
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            connect_timeout=10,
            request_timeout=30,
            follow_redirects=False,
            streaming_callback=receive,
        )
        try:
            response = await AsyncHTTPClient().fetch(request, raise_error=False)
        except Exception as exc:
            LOGGER.exception("aliyun tts request failed", extra={"event": "tts_aliyun_failed"})
            raise TTSServiceError("语音合成服务连接失败") from exc
        if response.code != 200:
            raise TTSServiceError(f"TTS 服务返回 HTTP {response.code}")
        return bytes(chunks)

    @staticmethod
    def _local_tts(text: str, voice: str) -> bytes:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            voices = engine.getProperty("voices")
            if voice.startswith("zh"):
                for v in voices:
                    if "zh" in v.language.lower():
                        engine.setProperty("voice", v.id)
                        break
            elif voice.startswith("en"):
                for v in voices:
                    if "en" in v.language.lower():
                        engine.setProperty("voice", v.id)
                        break
            engine.setProperty("rate", 150)
            engine.setProperty("volume", 1.0)
            temp_file = _cache_path(_text_hash(text, voice))
            engine.save_to_file(text, temp_file)
            engine.runAndWait()
            data = _read_file(temp_file)
            if data:
                return data
            raise TTSServiceError("本地语音合成失败")
        except ImportError:
            raise TTSConfigurationError("本地 TTS 需要安装 pyttsx3")
        except Exception as exc:
            LOGGER.exception("local tts failed", extra={"event": "tts_local_failed"})
            raise TTSServiceError("本地语音合成失败") from exc