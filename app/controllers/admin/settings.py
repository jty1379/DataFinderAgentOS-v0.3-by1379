"""后台系统设置控制器。"""

from app.controllers.base import AdminBaseHandler
from app.services.security import AuditLogService
from app.services.system_settings import SystemSettingsService


def _audit_setting_values(before: dict | None, after: dict | None) -> tuple[str, str]:
    """Mask both sides when either snapshot classifies the setting as sensitive."""
    sensitive = bool(
        (before and before.get("is_sensitive"))
        or (after and after.get("is_sensitive"))
    )
    if sensitive:
        return "***", "***"
    return (
        str((before or {}).get("setting_value", "")),
        str((after or {}).get("setting_value", "")),
    )


class AdminSettingsHandler(AdminBaseHandler):
    required_feature = "system_settings"

    def get(self) -> None:
        settings_list = SystemSettingsService.get_all_settings()
        settings = {s['setting_key']: s['setting_value'] for s in settings_list}
        self.render_admin(
            "admin/settings.html",
            title="系统设置 · 零界",
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
        before_value, after_value = _audit_setting_values(before, after)
        AuditLogService.log_action(
            "update", "setting", after["id"] if after else None,
            self.current_user["id"], self.current_user["username"], self.get_client_ip(),
            {"key": setting_key, "value": before_value},
            {"key": setting_key, "value": after_value},
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
            before_value, after_value = _audit_setting_values(before[key], after)
            AuditLogService.log_action(
                "update", "setting", after["id"] if after else None,
                self.current_user["id"], self.current_user["username"], self.get_client_ip(),
                {"key": key, "value": before_value},
                {"key": key, "value": after_value},
                "系统设置批量更新",
            )
        return f"已更新 {updated_count} 项设置", "success"
