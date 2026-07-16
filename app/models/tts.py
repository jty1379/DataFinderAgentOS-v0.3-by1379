"""语音合成配置与调用日志 Repository。"""

from __future__ import annotations

import sqlite3

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
        enabled = bool(values.get("enabled", False))
        provider = str(values.get("provider", "volcengine")).lower()
        default_voice = str(values.get("default_voice", "zh_female"))
        api_key_env = str(values.get("api_key_env", ""))
        api_secret_env = str(values.get("api_secret_env", ""))
        base_url = str(values.get("base_url", ""))
        rate = int(values.get("rate", 0))
        volume = int(values.get("volume", 0))
        pitch = int(values.get("pitch", 0))
        with connection_scope() as connection:
            cursor = connection.execute(
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