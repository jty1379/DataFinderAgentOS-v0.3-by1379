"""系统设置服务。"""

from __future__ import annotations

import logging

from app.models.system_settings import SystemSettingsRepository

LOGGER = logging.getLogger("app")


class SystemSettingsService:
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
        result = SystemSettingsRepository.set(key, value, user_id)
        if result:
            LOGGER.info("系统设置更新: %s = %s", key, "***" if key.startswith("secret") else value,
                        extra={"event": "system_setting_updated", "key": key, "user_id": user_id})
        return result

    @staticmethod
    def batch_update(settings: dict, user_id: int | None = None) -> int:
        setting_list = [(k, str(v)) for k, v in settings.items()]
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