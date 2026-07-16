"""系统设置服务。"""

from __future__ import annotations

import json
import logging
import re

from app.models.system_settings import SystemSettingsRepository

LOGGER = logging.getLogger("app")


class SystemSettingsService:
    INTEGER_RANGES = {
        "screen_refresh_interval": (5, 3600),
        "default_collect_timeout": (3, 120),
        "max_collect_count": (1, 1000),
        "max_upload_size": (1024 * 1024, 100 * 1024 * 1024),
        "sensitive_word_threshold": (1, 100),
        "session_timeout_minutes": (5, 10080),
        "session_inactivity_timeout_minutes": (1, 1440),
    }

    @staticmethod
    def validate(key: str, value) -> str:
        setting = SystemSettingsRepository.get(key)
        if not setting:
            raise ValueError(f"未知系统设置：{key}")
        raw = str(value).strip()
        setting_type = str(setting.get("setting_type") or "string")
        if setting_type == "boolean":
            lowered = raw.lower()
            if lowered not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
                raise ValueError(f"{key} 必须是布尔值")
            return "true" if lowered in {"true", "1", "yes", "on"} else "false"
        if setting_type == "integer":
            try:
                number = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} 必须是整数") from exc
            minimum, maximum = SystemSettingsService.INTEGER_RANGES.get(
                key, (-2_147_483_648, 2_147_483_647)
            )
            if not minimum <= number <= maximum:
                raise ValueError(f"{key} 必须在 {minimum}—{maximum} 之间")
            return str(number)
        if setting_type == "float":
            try:
                return str(float(raw))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} 必须是数字") from exc
        if setting_type == "json":
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{key} 必须是有效 JSON") from exc
            return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        if len(raw) > 1000:
            raise ValueError(f"{key} 不能超过 1000 个字符")
        if key == "default_model" and raw and not raw.isdecimal():
            raise ValueError("default_model 必须是模型 ID 或留空")
        if setting.get("is_sensitive") and raw and not re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", raw):
            raise ValueError(f"{key} 只能保存环境变量名称，不能直接保存密钥")
        return raw
    @staticmethod
    def get_all_settings() -> list[dict]:
        return SystemSettingsRepository.list_settings()

    @staticmethod
    def get_setting(key: str):
        return SystemSettingsRepository.get(key)

    @staticmethod
    def get_value(key: str, default: str = "") -> str:
        return SystemSettingsRepository.get_value(key, default)

    @staticmethod
    def get_boolean(key: str, default: bool = False) -> bool:
        return SystemSettingsRepository.get_boolean(key, default)

    @staticmethod
    def get_integer(key: str, default: int = 0) -> int:
        return SystemSettingsRepository.get_integer(key, default)

    @staticmethod
    def get_float(key: str, default: float = 0.0) -> float:
        return SystemSettingsRepository.get_float(key, default)

    @staticmethod
    def update_setting(key: str, value: str, user_id: int | None = None) -> bool:
        normalized = SystemSettingsService.validate(key, value)
        result = SystemSettingsRepository.set(key, normalized, user_id)
        if result:
            LOGGER.info("系统设置更新: %s = %s", key, "***" if SystemSettingsRepository.get(key).get("is_sensitive") else normalized,
                        extra={"event": "system_setting_updated", "key": key, "user_id": user_id})
        return result

    @staticmethod
    def batch_update(settings: dict, user_id: int | None = None) -> int:
        setting_list = [(k, SystemSettingsService.validate(k, v)) for k, v in settings.items()]
        return SystemSettingsRepository.batch_set(setting_list, user_id)

    @staticmethod
    def is_maintenance_mode() -> bool:
        return SystemSettingsRepository.get_boolean("maintenance_mode", False)

    @staticmethod
    def allow_register() -> bool:
        return SystemSettingsRepository.get_boolean("allow_register", True)

    @staticmethod
    def get_system_name() -> str:
        return SystemSettingsRepository.get_value("system_name", "智能瞭望与智能问数系统")

    @staticmethod
    def get_home_announcement() -> str:
        return SystemSettingsRepository.get_value("home_announcement", "")

    @staticmethod
    def get_screen_refresh_interval() -> int:
        return SystemSettingsRepository.get_integer("screen_refresh_interval", 30)

    @staticmethod
    def get_default_model() -> dict | None:
        from app.models.model_engine import ModelRepository

        configured = SystemSettingsRepository.get_value("default_model", "").strip()
        if configured.isdecimal():
            model = ModelRepository.get(int(configured))
            if model and model.get("enabled") and model.get("model_type") in {"text", "multimodal"}:
                return model
        return ModelRepository.get_default()
