"""语音合成服务。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import time

from tornado.httpclient import HTTPRequest

from app.core.net_guard import guarded_fetch
from app.models.tts import TTSCallRepository, TTSConfigRepository
from config.settings import BASE_DIR, SETTINGS

LOGGER = logging.getLogger("tts")


class TTSServiceError(ValueError):
    """TTS 服务调用错误。"""


class TTSConfigurationError(TTSServiceError):
    """TTS 配置错误。"""


CHUNK_SIZE = 500
MAX_TEXT_LENGTH = 5000
MINIMAX_TTS_MODEL = "speech-2.8-hd"


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
    cache_dir = BASE_DIR / "data" / "tts_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return str(cache_dir / f"{text_hash}.mp3")


def _text_hash(text: str, voice: str, config: dict | None = None) -> str:
    config = config or {}
    fingerprint = ":".join(
        str(config.get(key, ""))
        for key in ("provider", "rate", "volume", "pitch", "base_url")
    )
    return hashlib.sha256(f"{voice}:{fingerprint}:{text}".encode()).hexdigest()


def _read_file(path: str) -> bytes | None:
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _write_file(path: str, data: bytes) -> bool:
    try:
        with open(path, "wb") as f:
            f.write(data)
        return True
    except OSError:
        return False


class TTSService:
    @staticmethod
    def get_config() -> dict:
        return TTSConfigRepository.get_config()

    @staticmethod
    def is_enabled() -> bool:
        return TTSService.get_config().get("enabled", False)

    @staticmethod
    async def synthesize(text: str, voice: str = "", user_id: int | None = None) -> dict:
        del user_id
        started = time.monotonic()
        config = TTSService.get_config()
        if not config.get("enabled"):
            TTSCallRepository.record(
                len(str(text or "")), voice or str(config.get("default_voice") or ""),
                success=False, error_message="语音合成服务未启用",
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            raise TTSServiceError("语音合成服务未启用")
        text = text.strip()
        if not 1 <= len(text) <= MAX_TEXT_LENGTH:
            TTSCallRepository.record(
                len(text), voice or str(config.get("default_voice") or ""),
                success=False, error_message=f"文本长度需为 1—{MAX_TEXT_LENGTH} 个字符",
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            raise TTSServiceError(f"文本长度需为 1—{MAX_TEXT_LENGTH} 个字符")
        voice = voice or config.get("default_voice", "zh_female")
        text_hash = _text_hash(text, voice, config)
        cache_file = _cache_path(text_hash)
        cached_data = _read_file(cache_file)
        if cached_data:
            result = {
                "ok": True,
                "audio_url": f"/tts/audio/{text_hash}.mp3",
                "from_cache": True,
                "length": len(cached_data),
                "voice": voice,
            }
            TTSCallRepository.record(
                len(text), voice, success=True, from_cache=True,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            return result
        chunks = _text_chunks(text)
        if not chunks:
            raise TTSServiceError("文本内容为空")
        try:
            audio_parts = []
            for chunk in chunks:
                part = await TTSService._synthesize_chunk(chunk, voice, config)
                audio_parts.append(part)
            combined = b"".join(audio_parts)
            if not combined or not _write_file(cache_file, combined):
                raise TTSServiceError("语音文件保存失败")
            result = {
                "ok": True,
                "audio_url": f"/tts/audio/{text_hash}.mp3",
                "from_cache": False,
                "length": len(combined),
                "voice": voice,
                "chunks": len(chunks),
            }
            TTSCallRepository.record(
                len(text), voice, success=True,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            return result
        except TTSServiceError as exc:
            TTSCallRepository.record(
                len(text), voice, success=False, error_message=str(exc),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            raise

    @staticmethod
    async def _synthesize_chunk(text: str, voice: str, config: dict) -> bytes:
        provider = config.get("provider", "volcengine")
        if provider == "minimax":
            return await TTSService._minimax_tts(text, voice, config)
        if provider == "volcengine":
            return await TTSService._volcengine_tts(text, voice, config)
        elif provider == "aliyun":
            return await TTSService._aliyun_tts(text, voice, config)
        elif provider == "local":
            # 将阻塞的 pyttsx3 调用卸载到线程池，避免阻塞事件循环
            return await asyncio.wait_for(
                asyncio.to_thread(TTSService._local_tts, text, voice, config),
                timeout=30
            )
        else:
            raise TTSConfigurationError(f"不支持的 TTS 提供商: {provider}")

    @staticmethod
    async def _minimax_tts(text: str, voice: str, config: dict) -> bytes:
        api_key = SETTINGS.secret_from_env(str(config.get("api_key_env", "")))
        if not api_key:
            raise TTSConfigurationError("MiniMax Token Plan Key 环境变量未配置")
        base_url = str(config.get("base_url") or "").strip().rstrip("/")
        if not base_url:
            raise TTSConfigurationError("MiniMax TTS 服务地址未配置")
        url = base_url if base_url.endswith("/t2a_v2") else base_url + "/t2a_v2"
        rate = max(-100, min(100, int(config.get("rate", 0))))
        volume = max(-100, min(100, int(config.get("volume", 0))))
        pitch = max(-100, min(100, int(config.get("pitch", 0))))
        payload = {
            "model": str(config.get("tts_model") or MINIMAX_TTS_MODEL),
            "text": text,
            "stream": False,
            "voice_setting": {
                "voice_id": voice or "male-qn-qingse",
                "speed": round(max(0.5, min(2.0, 1 + rate / 100)), 2),
                "vol": round(max(0.1, min(10.0, 1 + volume / 20)), 2),
                "pitch": round(pitch * 12 / 100),
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
            "language_boost": "auto",
            "output_format": "hex",
        }
        chunks = bytearray()

        def receive(chunk: bytes) -> None:
            if len(chunks) + len(chunk) > 6 * 1024 * 1024:
                raise TTSServiceError("MiniMax TTS 响应超过 6MB 限制")
            chunks.extend(chunk)

        try:
            response = await guarded_fetch(
                HTTPRequest(
                    url=url,
                    method="POST",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    connect_timeout=15,
                    request_timeout=90,
                    follow_redirects=False,
                    streaming_callback=receive,
                ),
                raise_error=False,
            )
        except TTSServiceError:
            raise
        except Exception as exc:
            LOGGER.exception("minimax tts request failed", extra={"event": "tts_minimax_failed"})
            raise TTSServiceError("MiniMax 语音合成服务连接失败") from exc
        try:
            data = json.loads(bytes(chunks).decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise TTSServiceError("MiniMax 语音服务未返回有效 JSON") from exc
        base_resp = data.get("base_resp") if isinstance(data, dict) else {}
        status_code = int(base_resp.get("status_code", -1)) if isinstance(base_resp, dict) else -1
        if response.code != 200 or status_code != 0:
            message = base_resp.get("status_msg", "") if isinstance(base_resp, dict) else ""
            raise TTSServiceError(str(message or f"MiniMax TTS 返回 HTTP {response.code}")[:500])
        audio_hex = str((data.get("data") or {}).get("audio") or "")
        try:
            audio = bytes.fromhex(audio_hex)
        except ValueError as exc:
            raise TTSServiceError("MiniMax TTS 返回的音频数据无效") from exc
        if not audio or len(audio) > 5 * 1024 * 1024:
            raise TTSServiceError("MiniMax TTS 返回的音频为空或超过限制")
        return audio

    @staticmethod
    async def _volcengine_tts(text: str, voice: str, config: dict) -> bytes:
        api_key = SETTINGS.secret_from_env(str(config.get("api_key_env", "")))
        api_secret = SETTINGS.secret_from_env(str(config.get("api_secret_env", "")))
        if not api_key or not api_secret:
            raise TTSConfigurationError("火山引擎 TTS API Key 或 Secret 未配置")
        import datetime
        import hmac
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        canonical_uri = "/api/text/speech"
        query_string = "Action=GetTts&Version=2023-04-01"
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
        base_url = str(config.get("base_url") or "").strip()
        if not base_url:
            raise TTSConfigurationError("火山引擎 TTS 服务地址未配置")
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
        try:
            response = await guarded_fetch(request, raise_error=False)
        except Exception as exc:
            LOGGER.exception("volcengine tts request failed", extra={"event": "tts_volcengine_failed"})
            raise TTSServiceError("语音合成服务连接失败") from exc
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
        import datetime
        import hmac
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
        base_url = str(config.get("base_url") or "").strip()
        if not base_url:
            raise TTSConfigurationError("阿里云 TTS 服务地址未配置")
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
            response = await guarded_fetch(request, raise_error=False)
        except Exception as exc:
            LOGGER.exception("aliyun tts request failed", extra={"event": "tts_aliyun_failed"})
            raise TTSServiceError("语音合成服务连接失败") from exc
        if response.code != 200:
            raise TTSServiceError(f"TTS 服务返回 HTTP {response.code}")
        return bytes(chunks)

    @staticmethod
    def _local_tts(text: str, voice: str, config: dict) -> bytes:
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
            engine.setProperty("rate", max(60, min(300, 150 + int(config.get("rate", 0)))))
            engine.setProperty(
                "volume", max(0.0, min(1.0, (int(config.get("volume", 0)) + 100) / 200))
            )
            temp_file = _cache_path(_text_hash(text, voice, config))
            engine.save_to_file(text, temp_file)
            engine.runAndWait()
            data = _read_file(temp_file)
            if data:
                return data
            raise TTSServiceError("本地语音合成失败")
        except ImportError as exc:
            raise TTSConfigurationError("本地 TTS 需要安装 pyttsx3") from exc
        except Exception as exc:
            LOGGER.exception("local tts failed", extra={"event": "tts_local_failed"})
            raise TTSServiceError("本地语音合成失败") from exc
