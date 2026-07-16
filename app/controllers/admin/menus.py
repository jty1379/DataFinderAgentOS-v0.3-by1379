"""后台菜单管理控制器。"""

from app.controllers.admin.common import ICON_PATTERN, integer, validate_text
from app.controllers.base import AdminBaseHandler
from app.repositories.feature_repository import FeatureRepository
from app.repositories.menu_repository import MenuRepository
from app.repositories.role_repository import RoleRepository


class AdminMenusHandler(AdminBaseHandler):
    required_feature = "menu_management"

    def get(self) -> None:
        keyword = self.get_query_argument("q", "").strip()
        menus = MenuRepository.list_menus(keyword)
        used = {item["feature_id"] for item in MenuRepository.list_menus()}
        available = [item for item in FeatureRepository.list_features() if item["id"] not in used and item["route"].startswith("/admin/")]
        roles = RoleRepository.list_roles()
        raw_role_id = self.get_query_argument("preview_role_id", str(self.current_user["role_id"]))
        preview_role_id = int(raw_role_id) if raw_role_id.isdecimal() else self.current_user["role_id"]
        selected = next((item for item in roles if item["id"] == preview_role_id), None)
        if not selected:
            preview_role_id = self.current_user["role_id"]
            selected = next(item for item in roles if item["id"] == preview_role_id)
        self.render_admin(
            "admin/menus.html",
            title="菜单管理 · 零界",
            active_menu="menu_management",
            menus=menus,
            available_features=available,
            preview_menus=MenuRepository.list_for_role(preview_role_id),
            preview_roles=roles,
            selected_preview_role=selected,
            selected_preview_role_id=preview_role_id,
            keyword=keyword,
        )

    def post(self) -> None:
        self.require_superadmin()
        action = self.get_body_argument("action", "")
        try:
            if action == "create":
                self._create()
                return self.redirect_with_message("/admin/menus", "菜单创建成功")
            menu_id = integer(self, "menu_id")
            menu = MenuRepository.get(menu_id)
            if not menu:
                raise ValueError("菜单不存在")
            message, level = self._change(action, menu_id, menu)
            self.redirect_with_message("/admin/menus", message, level)
        except ValueError as exc:
            self.redirect_with_message("/admin/menus", str(exc), "error")

    def _fields(self) -> tuple[str, str, str, int]:
        title = validate_text(self.get_body_argument("title", ""), "菜单名称", 2, 30)
        icon = self.get_body_argument("icon", "layui-icon-app").strip()
        category = validate_text(self.get_body_argument("category", ""), "菜单分组", 2, 30)
        sort_order = integer(self, "sort_order", 100)
        if not ICON_PATTERN.fullmatch(icon):
            raise ValueError("图标格式不正确")
        return title, icon, category, sort_order

    def _create(self) -> None:
        if not MenuRepository.create(integer(self, "feature_id"), *self._fields()):
            raise ValueError("该功能已有菜单或功能不存在")

    def _change(self, action: str, menu_id: int, menu: dict) -> tuple[str, str]:
        if action == "update":
            MenuRepository.update(menu_id, *self._fields())
            return "菜单信息已更新", "success"
        if action == "toggle":
            MenuRepository.set_enabled(menu_id, not bool(menu["enabled"]))
            return "菜单显示状态已更新", "success"
        if action in {"up", "down"}:
            moved = MenuRepository.move(menu_id, action)
            return "菜单顺序已调整" if moved else "已经到达边界", "success"
        if action == "delete":
            ok, message = MenuRepository.delete(menu_id)
            return message, "success" if ok else "error"
        raise ValueError("未知操作")
