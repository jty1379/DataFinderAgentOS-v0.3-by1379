"""后台系统设置控制器。"""

from app.controllers.admin.common import integer
from app.controllers.base import AdminBaseHandler
from app.services.system_settings import SystemSettingsService


class AdminSettingsHandler(AdminBaseHandler):
    required_feature = "system_settings"

    def get(self) -> None:
        settings = SystemSettingsService.get_all_settings()
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
        if not SystemSettingsService.update_setting(setting_key, setting_value, self.current_user["id"]):
            raise ValueError("保存失败")
        return "设置已更新", "success"

    def _batch_update(self) -> tuple[str, str]:
        setting_keys = self.get_body_arguments("setting_keys")
        setting_values = self.get_body_arguments("setting_values")
        if len(setting_keys) != len(setting_values):
            raise ValueError("参数数量不匹配")
        settings_dict = dict(zip(setting_keys, setting_values))
        updated_count = SystemSettingsService.batch_update(settings_dict, self.current_user["id"])
        return f"已更新 {updated_count} 项设置", "success"