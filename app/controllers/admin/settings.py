"""后台系统设置控制器。"""

from app.controllers.base import AdminBaseHandler
from app.services.security import AuditLogService
from app.services.system_settings import SystemSettingsService


class AdminSettingsHandler(AdminBaseHandler):
    required_feature = "system_settings"

    def get(self) -> None:
        settings_list = SystemSettingsService.get_all_settings()
        settings = {s['setting_key']: s['setting_value'] for s in settings_list}
        self.render_admin(
            "admin/settings.html",
            title="系统设置 · 瞭望与问数系统",
            active_menu="system_settings",
            settings=settings,
        )

    def post(self) -> None:
        self.require_superadmin()
        action = self.get_body_argument("action", "")
        try:
            handlers = {
                "update": self._update,
                "batch_update": self._batch_update,
            }
            if action not in handlers:
                raise ValueError("未知操作")
            message, level = handlers[action]()
            self.redirect_with_message("/admin/settings", message, level)
        except ValueError as exc:
            self.redirect_with_message("/admin/settings", str(exc), "error")

    def _update(self) -> tuple[str, str]:
        setting_key = self.get_body_argument("setting_key", "").strip()
        setting_value = self.get_body_argument("setting_value", "").strip()
        if not setting_key:
            raise ValueError("设置键不能为空")
        before = SystemSettingsService.get_setting(setting_key)
        if not SystemSettingsService.update_setting(setting_key, setting_value, self.current_user["id"]):
            raise ValueError("保存失败")
        after = SystemSettingsService.get_setting(setting_key)
        sensitive = bool(after and after.get("is_sensitive"))
        AuditLogService.log_action(
            "update", "setting", after["id"] if after else None,
            self.current_user["id"], self.current_user["username"], self.get_client_ip(),
            {"key": setting_key, "value": "***" if sensitive else (before or {}).get("setting_value", "")},
            {"key": setting_key, "value": "***" if sensitive else (after or {}).get("setting_value", "")},
            "系统设置单项更新",
        )
        return "设置已更新", "success"

    def _batch_update(self) -> tuple[str, str]:
        boolean_keys = {
            "allow_register", "enable_face_login", "enable_voice_report", "maintenance_mode"
        }
        editable_keys = (
            "system_name", "system_logo", "system_description", "home_announcement",
            "default_model", "allow_register", "enable_face_login", "enable_voice_report",
            "sensitive_word_threshold", "screen_refresh_interval", "default_collect_timeout",
            "max_collect_count", "max_upload_size", "maintenance_mode",
            "session_timeout_minutes", "session_inactivity_timeout_minutes",
        )
        settings_dict = {
            key: self.get_body_argument(f"setting_{key}", "false" if key in boolean_keys else "")
            for key in editable_keys
        }
        before = {key: SystemSettingsService.get_setting(key) for key in settings_dict}
        updated_count = SystemSettingsService.batch_update(settings_dict, self.current_user["id"])
        for key in settings_dict:
            after = SystemSettingsService.get_setting(key)
            sensitive = bool(after and after.get("is_sensitive"))
            AuditLogService.log_action(
                "update", "setting", after["id"] if after else None,
                self.current_user["id"], self.current_user["username"], self.get_client_ip(),
                {"key": key, "value": "***" if sensitive else (before[key] or {}).get("setting_value", "")},
                {"key": key, "value": "***" if sensitive else (after or {}).get("setting_value", "")},
                "系统设置批量更新",
            )
        return f"已更新 {updated_count} 项设置", "success"
