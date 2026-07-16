"""后台功能权限控制器。"""

from app.controllers.admin.common import (
    CODE_PATTERN,
    ICON_PATTERN,
    integer,
    pager_context,
    query_page,
    validate_text,
)
from app.controllers.base import AdminBaseHandler
from app.repositories.feature_repository import FeatureRepository


class AdminFeaturesHandler(AdminBaseHandler):
    required_feature = "feature_management"

    def get(self) -> None:
        keyword = self.get_query_argument("q", "").strip()
        enabled = self.get_query_argument("enabled", "").strip()
        features, pager = FeatureRepository.paginate_features(keyword, enabled, query_page(self), 20)
        roots = [item for item in FeatureRepository.list_features() if not item.get("parent_id")]
        self.render_admin(
            "admin/features.html",
            title="功能管理 · 瞭望与问数系统",
            active_menu="feature_management",
            features=features,
            root_features=roots,
            parent_candidates=roots,
            pager=pager_context("/admin/features", pager, q=keyword, enabled=enabled),
            keyword=keyword,
            selected_enabled=enabled,
        )

    def post(self) -> None:
        self.require_superadmin()
        action = self.get_body_argument("action", "")
        try:
            if action == "create":
                self._create()
                return self.redirect_with_message("/admin/features", "功能创建成功")
            feature_id = integer(self, "feature_id")
            feature = FeatureRepository.get(feature_id)
            if not feature:
                raise ValueError("功能不存在")
            message, destination, level = self._change(action, feature_id, feature)
            self.redirect_with_message(destination, message, level)
        except ValueError as exc:
            self.redirect_with_message("/admin/features", str(exc), "error")

    def _fields(self) -> tuple[str, str, str, str, str, int, int | None]:
        name = validate_text(self.get_body_argument("name", ""), "功能名称", 2, 30)
        route = self.get_body_argument("route", "").strip()
        icon = self.get_body_argument("icon", "layui-icon-app").strip()
        category = validate_text(self.get_body_argument("category", ""), "功能分组", 2, 30)
        description = self.get_body_argument("description", "").strip()[:200]
        sort_order = integer(self, "sort_order", 100)
        parent_id = integer(self, "parent_id", 0) or None
        if not route.startswith("/") or not ICON_PATTERN.fullmatch(icon):
            raise ValueError("路由或图标格式不正确")
        return name, route, icon, category, description, sort_order, parent_id

    def _create(self) -> None:
        code = self.get_body_argument("code", "").strip()
        fields = self._fields()
        if not CODE_PATTERN.fullmatch(code):
            raise ValueError("功能编码格式不正确")
        if not FeatureRepository.create(code, *fields):
            raise ValueError("功能编码、路由或父级关系无效")

    def _change(self, action: str, feature_id: int, feature: dict) -> tuple[str, str, str]:
        if action == "update":
            if not FeatureRepository.update(feature_id, *self._fields()):
                raise ValueError("保存失败，路由或父级关系无效")
            return "功能信息已更新", "/admin/features", "success"
        if action == "toggle":
            enabled = not bool(feature["enabled"])
            FeatureRepository.set_enabled(feature_id, enabled)
            destination = "/admin/" if feature["code"] == self.required_feature and not enabled else "/admin/features"
            return "功能已启用" if enabled else "功能已禁用", destination, "success"
        if action == "delete":
            ok, message = FeatureRepository.delete(feature_id)
            return message, "/admin/features", "success" if ok else "error"
        raise ValueError("未知操作")
