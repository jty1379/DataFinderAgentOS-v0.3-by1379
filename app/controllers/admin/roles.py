"""后台角色和功能授权控制器。"""

import json

from app.controllers.admin.common import (
    CODE_PATTERN,
    integer,
    layui_feature_tree,
    pager_context,
    positive_integers,
    query_page,
    validate_text,
)
from app.controllers.base import AdminBaseHandler
from app.repositories.feature_repository import FeatureRepository
from app.repositories.role_repository import RoleRepository


class AdminRolesHandler(AdminBaseHandler):
    required_feature = "role_management"

    def get(self) -> None:
        keyword = self.get_query_argument("q", "").strip()
        roles, pager = RoleRepository.paginate_roles(keyword, query_page(self), 20)
        for role in roles:
            role["feature_ids"] = RoleRepository.feature_ids(role["id"])
        tree = layui_feature_tree(FeatureRepository.tree_features())
        self.render_admin(
            "admin/roles.html",
            title="角色管理 · 瞭望与问数系统",
            active_menu="role_management",
            roles=roles,
            features=FeatureRepository.list_features(),
            feature_tree_json=json.dumps(tree, ensure_ascii=False).replace("</", "<\\/"),
            pager=pager_context("/admin/roles", pager, q=keyword),
            keyword=keyword,
        )

    def post(self) -> None:
        self.require_superadmin()
        action = self.get_body_argument("action", "")
        try:
            if action == "create":
                self._create()
                return self.redirect_with_message("/admin/roles", "角色创建成功")
            role_id = integer(self, "role_id")
            role = RoleRepository.get(role_id)
            if not role:
                raise ValueError("角色不存在")
            if role["code"] == "admin" and action in {"update", "permissions", "delete"}:
                raise ValueError("系统管理员为默认受保护角色，不允许修改、授权或删除")
            message, level = self._change(action, role_id, role)
            self.redirect_with_message("/admin/roles", message, level)
        except ValueError as exc:
            self.redirect_with_message("/admin/roles", str(exc), "error")

    def _create(self) -> None:
        code = self.get_body_argument("code", "").strip()
        name = validate_text(self.get_body_argument("name", ""), "角色名称", 2, 30)
        description = self.get_body_argument("description", "").strip()[:200]
        scope = self.get_body_argument("access_scope", "user")
        if not CODE_PATTERN.fullmatch(code) or scope not in {"user", "admin"}:
            raise ValueError("角色编码或访问端无效")
        if not RoleRepository.create(code, name, description, scope):
            raise ValueError("角色编码已存在")

    def _change(self, action: str, role_id: int, role: dict) -> tuple[str, str]:
        if action == "update":
            name = validate_text(self.get_body_argument("name", ""), "角色名称", 2, 30)
            description = self.get_body_argument("description", "").strip()[:200]
            scope = self.get_body_argument("access_scope", role["access_scope"])
            enabled = self.get_body_argument("enabled", "1") == "1"
            if scope not in {"user", "admin"}:
                raise ValueError("访问端无效")
            if role_id == self.current_user["role_id"] and not enabled:
                raise ValueError("不能停用当前账号所属角色")
            if not RoleRepository.update(role_id, name, description, scope, enabled):
                raise ValueError("角色保存失败，系统保护规则不允许该修改")
            return "角色信息已更新", "success"
        if action == "permissions":
            feature_ids = positive_integers(self.get_body_arguments("feature_ids"))
            if role_id == self.current_user["role_id"]:
                core = {"dashboard", "role_management"}
                feature_ids.extend(item["id"] for item in FeatureRepository.list_features() if item["code"] in core)
            if not RoleRepository.set_features(role_id, sorted(set(feature_ids))):
                raise ValueError("角色授权失败，系统管理员角色不允许修改")
            return "角色功能权限已保存", "success"
        if action == "delete":
            ok, message = RoleRepository.delete(role_id)
            return message, "success" if ok else "error"
        raise ValueError("未知操作")
