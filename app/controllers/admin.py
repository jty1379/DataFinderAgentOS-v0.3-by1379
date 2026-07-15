"""管理侧用户、角色、功能与菜单模块。"""

from __future__ import annotations

import json
import re
import urllib.parse

import tornado.web

from app.controllers.base import AdminBaseHandler
from app.models.rbac import FeatureRepository, MenuRepository, RoleRepository
from app.models.user import UserRepository


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff]{3,20}$")
CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
ICON_PATTERN = re.compile(r"^layui-icon-[a-z0-9-]+$")


def _integer(handler: tornado.web.RequestHandler, name: str, default: int = 0) -> int:
    try:
        return int(handler.get_body_argument(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc


def _query_page(handler: tornado.web.RequestHandler) -> int:
    """Read a positive page number without letting malformed URLs break a page."""
    try:
        return max(1, int(handler.get_query_argument("page", "1")))
    except ValueError:
        return 1


def _pager_context(path: str, pager: dict, **filters: object) -> dict:
    """Add stable navigation URLs to a repository pagination result."""
    page = int(pager.get("page", 1))
    pages = max(1, int(pager.get("total_pages", pager.get("pages", 1))))
    clean_filters = {
        key: value
        for key, value in filters.items()
        if value not in (None, "", 0, "0")
    }

    def page_url(number: int) -> str:
        query = urllib.parse.urlencode({**clean_filters, "page": number})
        return f"{path}?{query}"

    start = max(1, min(page - 2, pages - 4))
    end = min(pages, start + 4)
    start = max(1, end - 4)
    result = dict(pager)
    result.update(
        {
            "page": page,
            "pages": pages,
            "total_pages": pages,
            "page_links": [
                {"number": number, "url": page_url(number), "current": number == page}
                for number in range(start, end + 1)
            ],
            "prev_url": page_url(page - 1) if page > 1 else "",
            "next_url": page_url(page + 1) if page < pages else "",
        }
    )
    return result


def _layui_feature_tree(
    nodes: list[dict], ancestor_enabled: bool = True
) -> list[dict]:
    """Translate repository feature hierarchy to Layui Tree node data."""
    result = []
    for node in nodes:
        available = ancestor_enabled and bool(node.get("enabled"))
        result.append(
            {
                "id": int(node["id"]),
                "title": f"{node['name']}（{node['code']}）",
                "disabled": not available,
                "spread": True,
                "children": _layui_feature_tree(
                    node.get("children", []), available
                ),
            }
        )
    return result


def _validate_text(value: str, label: str, minimum: int = 1, maximum: int = 40) -> str:
    value = value.strip()
    if not minimum <= len(value) <= maximum:
        raise ValueError(f"{label}长度需为 {minimum}—{maximum} 个字符")
    return value


class AdminUsersHandler(AdminBaseHandler):
    required_feature = "user_management"

    def get(self):
        keyword = self.get_query_argument("q", "").strip()
        status = self.get_query_argument("status", "").strip()
        try:
            role_id = int(self.get_query_argument("role_id", "0")) or None
        except ValueError:
            role_id = None
        users, pager = UserRepository.paginate_users(
            keyword, role_id, status, _query_page(self), 20
        )
        self.render_admin(
            "admin/users.html",
            title="用户管理 · 瞭望与问数系统",
            active_menu="user_management",
            users=users,
            roles=RoleRepository.list_roles(),
            pager=_pager_context(
                "/admin/users", pager, q=keyword, role_id=role_id, status=status
            ),
            keyword=keyword,
            selected_role_id=role_id or 0,
            selected_status=status,
        )

    def post(self):
        self.require_superadmin()
        action = self.get_body_argument("action", "")
        try:
            if action == "change_superadmin_password":
                current_password = self.get_body_argument("current_password", "")
                new_password = self.get_body_argument("new_password", "")
                confirm_password = self.get_body_argument("confirm_password", "")
                if new_password != confirm_password:
                    raise ValueError("两次输入的新密码不一致")
                if current_password == new_password:
                    raise ValueError("新密码不能与当前密码相同")
                if not UserRepository.change_superadmin_password(
                    self.current_user["id"], current_password, new_password
                ):
                    raise ValueError("当前密码错误，或新密码不符合 6—64 位要求")
                return self.redirect_with_message("/admin/users", "超级管理员密码已更新")

            if action == "create":
                username = self.get_body_argument("username", "").strip()
                password = self.get_body_argument("password", "")
                role_id = _integer(self, "role_id")
                if not USERNAME_PATTERN.fullmatch(username):
                    raise ValueError("用户名需为 3—20 位中文、字母、数字或下划线")
                if not 6 <= len(password) <= 64:
                    raise ValueError("密码长度需为 6—64 位")
                if not UserRepository.create_user(username, password, role_id=role_id):
                    raise ValueError("用户名已存在或所选角色不可用")
                return self.redirect_with_message("/admin/users", "用户创建成功")

            if action == "batch":
                batch_action = self.get_body_argument("batch_action", "")
                if batch_action not in {"enable", "disable", "delete"}:
                    raise ValueError("请选择有效的批量操作")
                user_ids: list[int] = []
                for value in self.get_body_arguments("user_ids"):
                    try:
                        user_id = int(value)
                    except ValueError:
                        continue
                    if user_id > 0:
                        user_ids.append(user_id)
                if not user_ids:
                    raise ValueError("请至少选择一个用户")
                changed, message = UserRepository.batch_action(
                    sorted(set(user_ids)), batch_action, self.current_user["id"]
                )
                return self.redirect_with_message(
                    "/admin/users",
                    message,
                    "success" if changed else "error",
                )

            user_id = _integer(self, "user_id")
            target = next((item for item in UserRepository.list_users() if item["id"] == user_id), None)
            if not target:
                raise ValueError("用户不存在")
            if action == "update":
                username = self.get_body_argument("username", "").strip()
                password = self.get_body_argument("password", "")
                role_id = _integer(self, "role_id")
                status = self.get_body_argument("status", "enabled")
                role = RoleRepository.get(role_id)
                if not USERNAME_PATTERN.fullmatch(username):
                    raise ValueError("用户名格式不正确")
                if password and not 6 <= len(password) <= 64:
                    raise ValueError("新密码长度需为 6—64 位")
                if status not in {"enabled", "disabled"} or not role:
                    raise ValueError("状态或角色无效")
                if target.get("is_superadmin"):
                    raise ValueError("默认超级管理员受系统保护，不能在用户列表中修改")
                removes_admin = status != "enabled" or role["access_scope"] != "admin"
                if UserRepository.is_enabled_admin(user_id) and removes_admin and UserRepository.count_enabled_admins() <= 1:
                    raise ValueError("必须至少保留一个可用管理员")
                if user_id == self.current_user["id"] and removes_admin:
                    raise ValueError("不能停用或降级当前登录账号")
                if not UserRepository.update_user(user_id, username, role_id, status, password):
                    raise ValueError("保存失败，用户名可能重复")
                return self.redirect_with_message("/admin/users", "用户信息已更新")
            if action == "delete":
                if target.get("is_superadmin"):
                    raise ValueError("默认超级管理员受系统保护，不能删除")
                if user_id == self.current_user["id"]:
                    raise ValueError("不能删除当前登录账号")
                if UserRepository.is_enabled_admin(user_id) and UserRepository.count_enabled_admins() <= 1:
                    raise ValueError("必须至少保留一个可用管理员")
                UserRepository.delete_user(user_id)
                return self.redirect_with_message("/admin/users", "用户已删除")
            raise ValueError("未知操作")
        except ValueError as exc:
            self.redirect_with_message("/admin/users", str(exc), "error")


class AdminRolesHandler(AdminBaseHandler):
    required_feature = "role_management"

    def get(self):
        keyword = self.get_query_argument("q", "").strip()
        roles, pager = RoleRepository.paginate_roles(keyword, _query_page(self), 20)
        for role in roles:
            role["feature_ids"] = RoleRepository.feature_ids(role["id"])
        feature_tree = _layui_feature_tree(FeatureRepository.tree_features())
        self.render_admin(
            "admin/roles.html",
            title="角色管理 · 瞭望与问数系统",
            active_menu="role_management",
            roles=roles,
            features=FeatureRepository.list_features(),
            feature_tree_json=json.dumps(feature_tree, ensure_ascii=False).replace(
                "</", "<\\/"
            ),
            pager=_pager_context("/admin/roles", pager, q=keyword),
            keyword=keyword,
        )

    def post(self):
        self.require_superadmin()
        action = self.get_body_argument("action", "")
        try:
            if action == "create":
                code = self.get_body_argument("code", "").strip()
                name = _validate_text(self.get_body_argument("name", ""), "角色名称", 2, 30)
                description = self.get_body_argument("description", "").strip()[:200]
                scope = self.get_body_argument("access_scope", "user")
                if not CODE_PATTERN.fullmatch(code) or scope not in {"user", "admin"}:
                    raise ValueError("角色编码或访问端无效")
                if not RoleRepository.create(code, name, description, scope):
                    raise ValueError("角色编码已存在")
                return self.redirect_with_message("/admin/roles", "角色创建成功")

            role_id = _integer(self, "role_id")
            role = RoleRepository.get(role_id)
            if not role:
                raise ValueError("角色不存在")
            if role["code"] == "admin" and action in {
                "update",
                "permissions",
                "delete",
            }:
                raise ValueError("系统管理员为默认受保护角色，不允许修改、授权或删除")
            if action == "update":
                name = _validate_text(self.get_body_argument("name", ""), "角色名称", 2, 30)
                description = self.get_body_argument("description", "").strip()[:200]
                scope = self.get_body_argument("access_scope", role["access_scope"])
                enabled = self.get_body_argument("enabled", "1") == "1"
                if scope not in {"user", "admin"}:
                    raise ValueError("访问端无效")
                if role_id == self.current_user["role_id"] and not enabled:
                    raise ValueError("不能停用当前账号所属角色")
                if not RoleRepository.update(
                    role_id, name, description, scope, enabled
                ):
                    raise ValueError("角色保存失败，系统保护规则不允许该修改")
                return self.redirect_with_message("/admin/roles", "角色信息已更新")
            if action == "permissions":
                feature_ids = []
                for value in self.get_body_arguments("feature_ids"):
                    try:
                        feature_ids.append(int(value))
                    except ValueError:
                        pass
                if role_id == self.current_user["role_id"]:
                    core_codes = {"dashboard", "role_management"}
                    feature_ids.extend(
                        item["id"] for item in FeatureRepository.list_features()
                        if item["code"] in core_codes
                    )
                if not RoleRepository.set_features(
                    role_id, sorted(set(feature_ids))
                ):
                    raise ValueError("角色授权失败，系统管理员角色不允许修改")
                return self.redirect_with_message("/admin/roles", "角色功能权限已保存")
            if action == "delete":
                ok, message = RoleRepository.delete(role_id)
                return self.redirect_with_message("/admin/roles", message, "success" if ok else "error")
            raise ValueError("未知操作")
        except ValueError as exc:
            self.redirect_with_message("/admin/roles", str(exc), "error")


class AdminFeaturesHandler(AdminBaseHandler):
    required_feature = "feature_management"

    def get(self):
        keyword = self.get_query_argument("q", "").strip()
        enabled = self.get_query_argument("enabled", "").strip()
        features, pager = FeatureRepository.paginate_features(
            keyword, enabled, _query_page(self), 20
        )
        all_features = FeatureRepository.list_features()
        root_features = [item for item in all_features if not item.get("parent_id")]
        self.render_admin(
            "admin/features.html",
            title="功能管理 · 瞭望与问数系统",
            active_menu="feature_management",
            features=features,
            root_features=root_features,
            parent_candidates=root_features,
            pager=_pager_context(
                "/admin/features", pager, q=keyword, enabled=enabled
            ),
            keyword=keyword,
            selected_enabled=enabled,
        )

    def post(self):
        self.require_superadmin()
        action = self.get_body_argument("action", "")
        try:
            if action == "create":
                code = self.get_body_argument("code", "").strip()
                name = _validate_text(self.get_body_argument("name", ""), "功能名称", 2, 30)
                route = self.get_body_argument("route", "").strip()
                icon = self.get_body_argument("icon", "layui-icon-app").strip()
                category = _validate_text(self.get_body_argument("category", ""), "功能分组", 2, 30)
                description = self.get_body_argument("description", "").strip()[:200]
                sort_order = _integer(self, "sort_order", 100)
                parent_id = _integer(self, "parent_id", 0) or None
                if not CODE_PATTERN.fullmatch(code) or not route.startswith("/") or not ICON_PATTERN.fullmatch(icon):
                    raise ValueError("功能编码、路由或图标格式不正确")
                if not FeatureRepository.create(
                    code, name, route, icon, category, description, sort_order, parent_id
                ):
                    raise ValueError("功能编码、路由或父级关系无效")
                return self.redirect_with_message("/admin/features", "功能创建成功")

            feature_id = _integer(self, "feature_id")
            feature = FeatureRepository.get(feature_id)
            if not feature:
                raise ValueError("功能不存在")
            if action == "update":
                name = _validate_text(self.get_body_argument("name", ""), "功能名称", 2, 30)
                route = self.get_body_argument("route", "").strip()
                icon = self.get_body_argument("icon", "layui-icon-app").strip()
                category = _validate_text(self.get_body_argument("category", ""), "功能分组", 2, 30)
                description = self.get_body_argument("description", "").strip()[:200]
                sort_order = _integer(self, "sort_order", 100)
                parent_id = _integer(self, "parent_id", 0) or None
                if not route.startswith("/") or not ICON_PATTERN.fullmatch(icon):
                    raise ValueError("路由或图标格式不正确")
                if not FeatureRepository.update(
                    feature_id, name, route, icon, category, description, sort_order, parent_id
                ):
                    raise ValueError("保存失败，路由或父级关系无效")
                return self.redirect_with_message("/admin/features", "功能信息已更新")
            if action == "toggle":
                enabled = not bool(feature["enabled"])
                FeatureRepository.set_enabled(feature_id, enabled)
                destination = "/admin/" if feature["code"] == self.required_feature and not enabled else "/admin/features"
                return self.redirect_with_message(destination, "功能已启用" if enabled else "功能已禁用")
            if action == "delete":
                ok, message = FeatureRepository.delete(feature_id)
                return self.redirect_with_message("/admin/features", message, "success" if ok else "error")
            raise ValueError("未知操作")
        except ValueError as exc:
            self.redirect_with_message("/admin/features", str(exc), "error")


class AdminMenusHandler(AdminBaseHandler):
    required_feature = "menu_management"

    def get(self):
        keyword = self.get_query_argument("q", "").strip()
        menus = MenuRepository.list_menus(keyword)
        used_feature_ids = {item["feature_id"] for item in MenuRepository.list_menus()}
        available_features = [
            item for item in FeatureRepository.list_features()
            if item["id"] not in used_feature_ids and item["route"].startswith("/admin/")
        ]
        preview_roles = RoleRepository.list_roles()
        try:
            preview_role_id = int(
                self.get_query_argument("preview_role_id", str(self.current_user["role_id"]))
            )
        except ValueError:
            preview_role_id = self.current_user["role_id"]
        selected_preview_role = next(
            (item for item in preview_roles if item["id"] == preview_role_id), None
        )
        if not selected_preview_role:
            preview_role_id = self.current_user["role_id"]
            selected_preview_role = next(
                item for item in preview_roles if item["id"] == preview_role_id
            )
        self.render_admin(
            "admin/menus.html",
            title="菜单管理 · 瞭望与问数系统",
            active_menu="menu_management",
            menus=menus,
            available_features=available_features,
            preview_menus=MenuRepository.list_for_role(preview_role_id),
            preview_roles=preview_roles,
            selected_preview_role=selected_preview_role,
            selected_preview_role_id=preview_role_id,
            keyword=keyword,
        )

    def post(self):
        self.require_superadmin()
        action = self.get_body_argument("action", "")
        try:
            if action == "create":
                feature_id = _integer(self, "feature_id")
                title = _validate_text(self.get_body_argument("title", ""), "菜单名称", 2, 30)
                icon = self.get_body_argument("icon", "layui-icon-app").strip()
                category = _validate_text(self.get_body_argument("category", ""), "菜单分组", 2, 30)
                sort_order = _integer(self, "sort_order", 100)
                if not ICON_PATTERN.fullmatch(icon):
                    raise ValueError("图标格式不正确")
                if not MenuRepository.create(feature_id, title, icon, category, sort_order):
                    raise ValueError("该功能已有菜单或功能不存在")
                return self.redirect_with_message("/admin/menus", "菜单创建成功")

            menu_id = _integer(self, "menu_id")
            menu = MenuRepository.get(menu_id)
            if not menu:
                raise ValueError("菜单不存在")
            if action == "update":
                title = _validate_text(self.get_body_argument("title", ""), "菜单名称", 2, 30)
                icon = self.get_body_argument("icon", "layui-icon-app").strip()
                category = _validate_text(self.get_body_argument("category", ""), "菜单分组", 2, 30)
                sort_order = _integer(self, "sort_order", 100)
                if not ICON_PATTERN.fullmatch(icon):
                    raise ValueError("图标格式不正确")
                MenuRepository.update(menu_id, title, icon, category, sort_order)
                return self.redirect_with_message("/admin/menus", "菜单信息已更新")
            if action == "toggle":
                MenuRepository.set_enabled(menu_id, not bool(menu["enabled"]))
                return self.redirect_with_message("/admin/menus", "菜单显示状态已更新")
            if action in {"up", "down"}:
                moved = MenuRepository.move(menu_id, action)
                return self.redirect_with_message("/admin/menus", "菜单顺序已调整" if moved else "已经到达边界")
            if action == "delete":
                ok, message = MenuRepository.delete(menu_id)
                return self.redirect_with_message("/admin/menus", message, "success" if ok else "error")
            raise ValueError("未知操作")
        except ValueError as exc:
            self.redirect_with_message("/admin/menus", str(exc), "error")


class AdminModuleHandler(AdminBaseHandler):
    LEGACY_REDIRECTS = {
        "lookout": "/admin/lookout",
        "data": "/admin/warehouse",
        "collect": "/admin/sources",
        "models": "/admin/models",
    }
    FEATURE_MAP = {
        "lookout": ("lookout_management", "瞭望采集", "该旧地址已迁移到独立采集工作台。"),
        "data": ("data_management", "数据仓库", "该旧地址已迁移到独立数据仓库。"),
        "collect": ("collection_management", "瞭源管理", "该旧地址已迁移到独立瞭源管理。"),
        "agents": ("digital_employees", "数字员工", "当前保留用户侧演示入口。"),
        "models": ("model_engine", "模型引擎", "该旧地址已迁移到独立模型引擎。"),
        "intelligence": ("intelligence_screen", "数智大屏", "大屏模板将在后续版本独立开发。"),
        "opinion": ("opinion_screen", "舆情大屏", "真实舆情采集与分析不在本次范围。"),
    }

    def get(self, module: str):
        if module in self.LEGACY_REDIRECTS:
            self.redirect(self.LEGACY_REDIRECTS[module], permanent=True)
            return
        item = self.FEATURE_MAP.get(module)
        if not item:
            raise tornado.web.HTTPError(404)
        code, title, note = item
        if not RoleRepository.has_feature(self.current_user["role_id"], code):
            raise tornado.web.HTTPError(403)
        self.render_admin(
            "admin/module.html",
            title=f"{title} · 瞭望与问数系统",
            active_menu=code,
            module_title=title,
            module_note=note,
        )
