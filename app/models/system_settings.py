"""系统设置 Repository。"""

from __future__ import annotations

import json

from app.models.db import connection_scope


DEFAULT_SETTINGS = [
    ("system_name", "智能瞭望与智能问数系统", "string", "系统名称", 0),
    ("system_logo", "", "string", "Logo地址", 0),
    ("system_description", "基于AI的数据采集、分析与智能问答系统", "string", "系统简介", 0),
    ("home_announcement", "", "string", "首页公告", 0),
    ("default_model", "", "string", "默认模型ID", 0),
    ("allow_register", "true", "boolean", "是否允许注册", 0),
    ("enable_face_login", "false", "boolean", "是否启用人脸登录", 0),
    ("enable_voice_report", "false", "boolean", "是否启用语音播报", 0),
    ("sensitive_word_threshold", "5", "integer", "敏感词阈值", 0),
    ("screen_refresh_interval", "30", "integer", "大屏刷新间隔(秒)", 0),
    ("default_collect_timeout", "30", "integer", "默认采集超时(秒)", 0),
    ("max_collect_count", "100", "integer", "单次采集最大数量", 0),
    ("max_upload_size", "52428800", "integer", "最大文件上传大小(字节)", 0),
    ("maintenance_mode", "false", "boolean", "系统维护模式", 0),
    ("session_timeout_minutes", "1440", "integer", "会话超时时间(分钟)", 0),
    ("session_inactivity_timeout_minutes", "30", "integer", "会话无活动超时(分钟)", 0),
]


class SystemSettingsRepository:
    @staticmethod
    def get(setting_key: str):
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT * FROM system_settings WHERE setting_key = ?",
                (setting_key,),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_value(setting_key: str, default: str = "") -> str:
        result = SystemSettingsRepository.get(setting_key)
        return result["setting_value"] if result else default

    @staticmethod
    def get_boolean(setting_key: str, default: bool = False) -> bool:
        value = SystemSettingsRepository.get_value(setting_key, str(default).lower())
        return value.lower() in ("true", "1", "yes", "on")

    @staticmethod
    def get_integer(setting_key: str, default: int = 0) -> int:
        value = SystemSettingsRepository.get_value(setting_key, str(default))
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def get_float(setting_key: str, default: float = 0.0) -> float:
        value = SystemSettingsRepository.get_value(setting_key, str(default))
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def get_json(setting_key: str, default: dict = None) -> dict:
        value = SystemSettingsRepository.get_value(setting_key, "{}")
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default or {}

    @staticmethod
    def list_settings() -> list[dict]:
        with connection_scope() as connection:
            rows = connection.execute(
                "SELECT * FROM system_settings ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def set(setting_key: str, setting_value: str, updated_by: int | None = None) -> bool:
        try:
            with connection_scope() as connection:
                existing = connection.execute(
                    "SELECT id FROM system_settings WHERE setting_key = ?",
                    (setting_key,),
                ).fetchone()
                if existing:
                    cursor = connection.execute(
                        """
                        UPDATE system_settings
                        SET setting_value = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE setting_key = ?
                        """,
                        (setting_value, updated_by, setting_key),
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO system_settings (setting_key, setting_value, updated_by)
                        VALUES (?, ?, ?)
                        """,
                        (setting_key, setting_value, updated_by),
                    )
                    cursor = type("Cursor", (), {"rowcount": 1})()
                connection.commit()
            return cursor.rowcount == 1
        except Exception:
            return False

    @staticmethod
    def batch_set(settings: list[tuple[str, str]], updated_by: int | None = None) -> int:
        count = 0
        with connection_scope() as connection:
            for setting_key, setting_value in settings:
                existing = connection.execute(
                    "SELECT id FROM system_settings WHERE setting_key = ?",
                    (setting_key,),
                ).fetchone()
                if existing:
                    cursor = connection.execute(
                        """
                        UPDATE system_settings
                        SET setting_value = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE setting_key = ?
                        """,
                        (setting_value, updated_by, setting_key),
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO system_settings (setting_key, setting_value, setting_type, description, is_sensitive, updated_by)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (setting_key, setting_value, "string", "", 0, updated_by),
                    )
                    cursor = type("Cursor", (), {"rowcount": 1})()
                if cursor.rowcount == 1:
                    count += 1
            connection.commit()
        return count

    @staticmethod
    def seed_defaults(connection) -> None:
        for key, value, setting_type, description, is_sensitive in DEFAULT_SETTINGS:
            connection.execute(
                """
                INSERT OR IGNORE INTO system_settings
                (setting_key, setting_value, setting_type, description, is_sensitive)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key, value, setting_type, description, is_sensitive),
            )