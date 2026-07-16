"""语音合成配置与调用日志 Repository。"""

from __future__ import annotations

import re
import sqlite3
from urllib.parse import urlsplit

from app.models.db import connection_scope


class TTSConfigRepository:
    @staticmethod
    def get_config() -> dict:
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT * FROM tts_config WHERE id = 1"
            ).fetchone()
            if row is None:
                return {
                    "enabled": False,
                    "provider": "volcengine",
                    "default_voice": "zh_female",
                    "api_key_env": "",
                    "api_secret_env": "",
                    "base_url": "",
                    "rate": 0,
                    "volume": 0,
                    "pitch": 0,
                }
            return dict(row)

    @staticmethod
    def update_config(**values) -> bool:
        raw_enabled = values.get("enabled", False)
        enabled = (
            raw_enabled.strip().lower() in {"1", "true", "yes", "on"}
            if isinstance(raw_enabled, str)
            else bool(raw_enabled)
        )
        provider = str(values.get("provider", "volcengine")).lower()
        if provider not in {"volcengine", "aliyun", "local"}:
            raise ValueError("不支持的 TTS 提供商")
        default_voice = str(values.get("default_voice", "zh_female")).strip()
        api_key_env = str(values.get("api_key_env", "")).strip()
        api_secret_env = str(values.get("api_secret_env", "")).strip()
        env_pattern = re.compile(r"^[A-Z_][A-Z0-9_]{1,79}$")
        for name in (api_key_env, api_secret_env):
            if name and not env_pattern.fullmatch(name):
                raise ValueError("密钥配置只能填写大写环境变量名称")
        base_url = str(values.get("base_url", "")).strip()
        if provider != "local" and base_url:
            parsed = urlsplit(base_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("外部 TTS 服务地址必须是无凭据的 HTTPS URL")
        rate = int(values.get("rate", 0))
        volume = int(values.get("volume", 0))
        pitch = int(values.get("pitch", 0))
        if not all(-100 <= value <= 100 for value in (rate, volume, pitch)):
            raise ValueError("语速、音量和音调需在 -100—100 之间")
        with connection_scope() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO tts_config
                    (id, enabled, provider, default_voice, api_key_env,
                     api_secret_env, base_url, rate, volume, pitch, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (enabled, provider, default_voice, api_key_env, api_secret_env, base_url, rate, volume, pitch),
            )
            connection.commit()
        return True


class TTSCallRepository:
    @staticmethod
    def record(
        text_length: int,
        voice: str,
        success: bool = True,
        error_message: str = "",
        latency_ms: int = 0,
        from_cache: bool = False,
    ) -> int | None:
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO tts_calls
                        (text_length, voice, success, error_message, latency_ms, from_cache)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (text_length, voice, int(bool(success)), error_message.strip()[:500], max(0, int(latency_ms)), int(bool(from_cache))),
                )
                connection.commit()
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None

    @staticmethod
    def stats() -> dict:
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_calls,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_calls,
                    SUM(CASE WHEN from_cache = 1 THEN 1 ELSE 0 END) AS cached_calls,
                    SUM(text_length) AS total_chars,
                    AVG(latency_ms) AS avg_latency_ms
                FROM tts_calls
                """
            ).fetchone()
        if row is None:
            return {
                "total_calls": 0,
                "success_calls": 0,
                "cached_calls": 0,
                "total_chars": 0,
                "avg_latency_ms": 0,
            }
        return {
            "total_calls": int(row["total_calls"] or 0),
            "success_calls": int(row["success_calls"] or 0),
            "cached_calls": int(row["cached_calls"] or 0),
            "total_chars": int(row["total_chars"] or 0),
            "avg_latency_ms": round(float(row["avg_latency_ms"] or 0), 1),
        }
