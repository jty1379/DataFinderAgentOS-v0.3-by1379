"""老师任务 2、2.1—2.4 的权限管理专项回归测试。"""

from __future__ import annotations

import importlib.util
import re
import tempfile
import unittest
import urllib.parse
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import patch

from tornado.testing import AsyncHTTPTestCase

from app.models import db
from app.models.rbac import FeatureRepository, MenuRepository, RoleRepository
from app.models.user import UserRepository

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRY_PATH = PROJECT_ROOT / "app.py"
ENTRY_SPEC = importlib.util.spec_from_file_location("datafinder_task2_entry", ENTRY_PATH)
ENTRY_MODULE = importlib.util.module_from_spec(ENTRY_SPEC)
assert ENTRY_SPEC and ENTRY_SPEC.loader
ENTRY_SPEC.loader.exec_module(ENTRY_MODULE)


class Task2RepositoryTest(unittest.TestCase):
    """直接验证数据库保护，确保伪造表单也不能绕过页面限制。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            db, "DATABASE_PATH", Path(self.temp_dir.name) / "task2-repository.db"
        )
        self.db_patch.start()
        db.init_db()
        UserRepository.ensure_admin("admin", "123456")

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_users_roles_and_features_use_twenty_item_pagination(self):
        user_role = RoleRepository.get_by_code("user")
        for index in range(25):
            self.assertTrue(
                UserRepository.create_user(
                    f"student{index:02d}", "123456", role_id=user_role["id"]
                )
            )

        first_users, user_pager = UserRepository.paginate_users(page=1)
        second_users, second_user_pager = UserRepository.paginate_users(page=2)
        self.assertEqual(len(first_users), 20)
        self.assertEqual(len(second_users), 6)  # 25 个测试用户 + 默认 admin
        self.assertEqual(user_pager["page_size"], 20)
        self.assertEqual(user_pager["total"], 26)
        self.assertEqual(second_user_pager["page"], 2)

        for index in range(21):
            self.assertTrue(
                RoleRepository.create(
                    f"audit{index:02d}", f"审计角色{index:02d}", "分页测试", "admin"
                )
            )
        first_roles, role_pager = RoleRepository.paginate_roles(page=1)
        last_roles, last_role_pager = RoleRepository.paginate_roles(page=999)
        self.assertEqual(len(first_roles), 20)
        self.assertEqual(role_pager["total"], 23)  # 21 个测试角色 + 两个内置角色
        self.assertEqual(last_role_pager["page"], 2)
        self.assertEqual(len(last_roles), 3)

        initial_feature_count = len(FeatureRepository.list_features())
        for index in range(9):
            self.assertTrue(
                FeatureRepository.create(
                    f"paging_feature_{index}",
                    f"分页功能{index}",
                    f"/admin/modules/paging-{index}",
                    "layui-icon-app",
                    "测试功能",
                    "功能分页测试",
                    300 + index,
                )
            )
        first_features, feature_pager = FeatureRepository.paginate_features(page=1)
        last_features, last_feature_pager = FeatureRepository.paginate_features(page=999)
        self.assertEqual(len(first_features), min(20, initial_feature_count + 9))
        self.assertEqual(feature_pager["total"], initial_feature_count + 9)
        self.assertEqual(
            len(last_features),
            (initial_feature_count + 9) - 20
            if initial_feature_count + 9 > 20
            else initial_feature_count + 9,
        )
        self.assertEqual(last_feature_pager["page"], feature_pager["total_pages"])

    def test_batch_operations_never_affect_superadmin(self):
        admin = UserRepository.get_superadmin()
        admin_role = RoleRepository.get_by_code("admin")
        user_role = RoleRepository.get_by_code("user")
        self.assertTrue(
            UserRepository.create_user("otheradmin", "123456", role_id=admin_role["id"])
        )
        self.assertTrue(
            UserRepository.create_user("batchuser", "123456", role_id=user_role["id"])
        )
        otheradmin = UserRepository.get_user_by_username("otheradmin")
        batchuser = UserRepository.get_user_by_username("batchuser")

        changed, message = UserRepository.batch_action(
            [admin["id"], otheradmin["id"]], "disable", admin["id"]
        )
        self.assertEqual(changed, 1)
        self.assertIn("超级管理员受保护", message)
        self.assertEqual(UserRepository.get_user_by_username("admin")["status"], "enabled")
        self.assertEqual(
            UserRepository.get_user_by_username("otheradmin")["status"], "disabled"
        )

        changed, message = UserRepository.batch_action(
            [admin["id"], batchuser["id"]], "delete", admin["id"]
        )
        self.assertEqual(changed, 1)
        self.assertIn("超级管理员受保护", message)
        self.assertIsNotNone(UserRepository.get_user_by_username("admin"))
        self.assertIsNone(UserRepository.get_user_by_username("batchuser"))

        changed, message = UserRepository.batch_action(
            [admin["id"]], "disable", otheradmin["id"]
        )
        self.assertEqual(changed, 0)
        self.assertIn("仅超级管理员", message)

    def test_superadmin_identity_is_locked_and_only_self_password_can_change(self):
        admin = UserRepository.get_superadmin()
        user_role = RoleRepository.get_by_code("user")
        original = dict(admin)

        self.assertFalse(
            UserRepository.update_user(
                admin["id"], "renamed", user_role["id"], "disabled", "654321"
            )
        )
        self.assertFalse(UserRepository.delete_user(admin["id"]))
        self.assertFalse(
            UserRepository.change_superadmin_password(admin["id"], "wrong-old", "654321")
        )
        self.assertIsNotNone(UserRepository.authenticate("admin", "123456"))
        self.assertTrue(
            UserRepository.change_superadmin_password(admin["id"], "123456", "654321")
        )
        self.assertIsNone(UserRepository.authenticate("admin", "123456"))
        self.assertIsNotNone(UserRepository.authenticate("admin", "654321"))

        changed = UserRepository.get_superadmin()
        for field in ("id", "username", "role_id", "role", "status", "is_superadmin"):
            self.assertEqual(changed[field], original[field])

        self.assertTrue(
            UserRepository.create_user("ordinary", "123456", role_id=user_role["id"])
        )
        ordinary = UserRepository.get_user_by_username("ordinary")
        self.assertFalse(
            UserRepository.change_superadmin_password(
                ordinary["id"], "123456", "another-password"
            )
        )

    def test_default_admin_role_is_fully_immutable(self):
        admin_role = RoleRepository.get_by_code("admin")
        original_feature_ids = RoleRepository.feature_ids(admin_role["id"])
        self.assertFalse(
            RoleRepository.update(
                admin_role["id"], "被篡改的角色", "越权修改", "user", False
            )
        )
        self.assertFalse(RoleRepository.set_features(admin_role["id"], []))
        deleted, message = RoleRepository.delete(admin_role["id"])
        self.assertFalse(deleted)
        self.assertIn("系统默认角色", message)

        unchanged = RoleRepository.get_by_code("admin")
        self.assertEqual(unchanged["name"], admin_role["name"])
        self.assertEqual(unchanged["access_scope"], "admin")
        self.assertTrue(unchanged["enabled"])
        self.assertEqual(RoleRepository.feature_ids(admin_role["id"]), original_feature_ids)

    def test_two_level_features_disabled_linkage_and_role_menu_preview(self):
        self.assertTrue(
            FeatureRepository.create(
                "audit_root",
                "审计中心",
                "/admin/modules/audit-root",
                "layui-icon-app",
                "测试功能",
                "一级功能",
                300,
            )
        )
        root = next(
            item for item in FeatureRepository.list_features() if item["code"] == "audit_root"
        )
        self.assertTrue(
            FeatureRepository.create(
                "audit_log",
                "审计日志",
                "/admin/modules/audit-log",
                "layui-icon-log",
                "测试功能",
                "二级功能",
                301,
                root["id"],
            )
        )
        child = next(
            item for item in FeatureRepository.list_features() if item["code"] == "audit_log"
        )
        self.assertEqual(child["parent_id"], root["id"])
        self.assertEqual(child["level"], 2)
        self.assertFalse(
            FeatureRepository.create(
                "audit_detail",
                "审计详情",
                "/admin/modules/audit-detail",
                "layui-icon-app",
                "测试功能",
                "禁止第三级",
                302,
                child["id"],
            )
        )
        self.assertFalse(
            FeatureRepository.update(
                root["id"],
                root["name"],
                root["route"],
                root["icon"],
                root["category"],
                root["description"],
                root["sort_order"],
                root["id"],
            )
        )

        tree = FeatureRepository.tree_features()
        tree_root = next(item for item in tree if item["id"] == root["id"])
        self.assertEqual([item["id"] for item in tree_root["children"]], [child["id"]])

        self.assertTrue(RoleRepository.create("auditor", "审计员", "只看审计", "admin"))
        auditor = RoleRepository.get_by_code("auditor")
        self.assertTrue(RoleRepository.set_features(auditor["id"], [child["id"]]))
        self.assertTrue(RoleRepository.has_feature(auditor["id"], "audit_log"))
        self.assertTrue(
            MenuRepository.create(
                child["id"], "审计日志", "layui-icon-log", "测试功能", 301
            )
        )
        self.assertEqual(
            [item["code"] for item in MenuRepository.list_for_role(auditor["id"])],
            ["audit_log"],
        )

        # 父功能停用时，二级功能即使自身仍启用也不能继续授权或生成菜单。
        self.assertTrue(FeatureRepository.set_enabled(root["id"], False))
        self.assertFalse(RoleRepository.has_feature(auditor["id"], "audit_log"))
        self.assertEqual(MenuRepository.list_for_role(auditor["id"]), [])
        self.assertTrue(RoleRepository.set_features(auditor["id"], [child["id"]]))
        self.assertNotIn(child["id"], RoleRepository.feature_ids(auditor["id"]))


class Task2HTTPTest(AsyncHTTPTestCase):
    """覆盖老师给出的 useradmin 实际登录链路与伪造请求。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            db, "DATABASE_PATH", Path(self.temp_dir.name) / "task2-http.db"
        )
        self.db_patch.start()
        db.init_db()
        UserRepository.ensure_admin("admin", "123456")

        self.assertTrue(
            RoleRepository.create(
                "useradmin", "用户管理员", "只读查看后台用户", "admin"
            )
        )
        useradmin_role = RoleRepository.get_by_code("useradmin")
        user_feature = next(
            item
            for item in FeatureRepository.list_features()
            if item["code"] == "user_management"
        )
        self.assertTrue(
            RoleRepository.set_features(useradmin_role["id"], [user_feature["id"]])
        )
        self.assertTrue(
            UserRepository.create_user(
                "useradmin", "admin888", role_id=useradmin_role["id"]
            )
        )
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def get_app(self):
        return ENTRY_MODULE.make_app()

    @staticmethod
    def _cookies_from(response):
        cookies = {}
        for value in response.headers.get_list("Set-Cookie"):
            parsed = SimpleCookie()
            parsed.load(value)
            for key, morsel in parsed.items():
                cookies[key] = morsel.value
        return cookies

    @staticmethod
    def _cookie_header(cookies):
        return "; ".join(f"{key}={value}" for key, value in cookies.items())

    def _form_context(self, path, cookies=None):
        current = dict(cookies or {})
        headers = {"Cookie": self._cookie_header(current)} if current else {}
        response = self.fetch(path, headers=headers)
        self.assertEqual(response.code, 200, response.body.decode("utf-8", errors="replace"))
        match = re.search(r'name="_xsrf" value="([^"]+)"', response.body.decode("utf-8"))
        self.assertIsNotNone(match, f"{path} 页面未输出 XSRF Token")
        current.update(self._cookies_from(response))
        return match.group(1), current

    def _post_form(self, path, values, token, cookies, follow_redirects=False):
        pairs = list(values.items()) if isinstance(values, dict) else list(values)
        pairs.append(("_xsrf", token))
        return self.fetch(
            path,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "Cookie": self._cookie_header(cookies),
            },
            body=urllib.parse.urlencode(pairs, doseq=True),
            follow_redirects=follow_redirects,
        )

    def _login(self, username, password):
        token, cookies = self._form_context("/admin/login")
        response = self._post_form(
            "/admin/login",
            {"username": username, "password": password},
            token,
            cookies,
        )
        self.assertEqual(response.code, 302)
        cookies.update(self._cookies_from(response))
        return response, cookies

    def test_task_2_1_useradmin_can_login_and_read_users_but_cannot_write(self):
        login, cookies = self._login("useradmin", "admin888")
        self.assertEqual(login.headers["Location"], "/admin/users")
        page = self.fetch(
            "/admin/users", headers={"Cookie": self._cookie_header(cookies)}
        )
        self.assertEqual(page.code, 200)
        self.assertIn("只读".encode(), page.body)

        # 只读页面没有任何 POST 表单，因此不会重复输出隐藏 Token；登录页
        # 已设置的同源 XSRF Cookie 仍可用于验证伪造写请求会被权限层拒绝。
        token = cookies["_xsrf"]
        admin = UserRepository.get_superadmin()
        for values in (
            {
                "action": "create",
                "username": "forged-user",
                "password": "123456",
                "role_id": admin["role_id"],
            },
            {
                "action": "update",
                "user_id": admin["id"],
                "username": "renamed-admin",
                "password": "654321",
                "role_id": admin["role_id"],
                "status": "disabled",
            },
            {"action": "delete", "user_id": admin["id"]},
            {
                "action": "batch",
                "batch_action": "delete",
                "user_ids": [admin["id"]],
            },
        ):
            response = self._post_form("/admin/users", values, token, cookies)
            self.assertEqual(response.code, 403, values["action"])

        unchanged = UserRepository.get_superadmin()
        self.assertEqual(unchanged["username"], "admin")
        self.assertEqual(unchanged["status"], "enabled")
        self.assertIsNotNone(UserRepository.authenticate("admin", "123456"))

    def test_task_2_2_and_2_4_admin_generic_edit_delete_and_batch_are_blocked(self):
        _, cookies = self._login("admin", "123456")
        token, cookies = self._form_context("/admin/users", cookies)
        admin = UserRepository.get_superadmin()
        user_role = RoleRepository.get_by_code("user")

        generic_update = self._post_form(
            "/admin/users",
            {
                "action": "update",
                "user_id": admin["id"],
                "username": "renamed-admin",
                "password": "654321",
                "role_id": user_role["id"],
                "status": "disabled",
            },
            token,
            cookies,
        )
        self.assertEqual(generic_update.code, 302)
        delete = self._post_form(
            "/admin/users",
            {"action": "delete", "user_id": admin["id"]},
            token,
            cookies,
        )
        self.assertEqual(delete.code, 302)
        batch = self._post_form(
            "/admin/users",
            {
                "action": "batch",
                "batch_action": "disable",
                "user_ids": [admin["id"]],
            },
            token,
            cookies,
        )
        self.assertEqual(batch.code, 302)

        unchanged = UserRepository.get_superadmin()
        self.assertEqual(unchanged["username"], "admin")
        self.assertEqual(unchanged["role_id"], admin["role_id"])
        self.assertEqual(unchanged["status"], "enabled")
        self.assertIsNotNone(UserRepository.authenticate("admin", "123456"))

    def test_task_2_4_only_admin_self_password_action_changes_password(self):
        _, cookies = self._login("admin", "123456")
        token, cookies = self._form_context("/admin/users", cookies)
        admin = UserRepository.get_superadmin()

        wrong_old = self._post_form(
            "/admin/users",
            {
                "action": "change_superadmin_password",
                "current_password": "wrong-old",
                "new_password": "654321",
                "confirm_password": "654321",
                # 这些伪造字段必须被专用动作忽略。
                "username": "renamed-admin",
                "role_id": RoleRepository.get_by_code("user")["id"],
                "status": "disabled",
            },
            token,
            cookies,
        )
        self.assertEqual(wrong_old.code, 302)
        self.assertIsNotNone(UserRepository.authenticate("admin", "123456"))

        changed = self._post_form(
            "/admin/users",
            {
                "action": "change_superadmin_password",
                "current_password": "123456",
                "new_password": "654321",
                "confirm_password": "654321",
            },
            token,
            cookies,
        )
        self.assertEqual(changed.code, 302)
        self.assertIsNone(UserRepository.authenticate("admin", "123456"))
        self.assertIsNotNone(UserRepository.authenticate("admin", "654321"))
        protected = UserRepository.get_superadmin()
        self.assertEqual(protected["id"], admin["id"])
        self.assertEqual(protected["username"], "admin")
        self.assertEqual(protected["role_id"], admin["role_id"])
        self.assertEqual(protected["status"], "enabled")

        # useradmin 即使复制专用 action，也在权限模块写入门禁处被拒绝。
        _, readonly_cookies = self._login("useradmin", "admin888")
        readonly_token = readonly_cookies["_xsrf"]
        forbidden = self._post_form(
            "/admin/users",
            {
                "action": "change_superadmin_password",
                "current_password": "654321",
                "new_password": "new-password",
                "confirm_password": "new-password",
            },
            readonly_token,
            readonly_cookies,
        )
        self.assertEqual(forbidden.code, 403)
        self.assertIsNotNone(UserRepository.authenticate("admin", "654321"))

    def test_default_admin_role_is_immutable_through_http(self):
        _, cookies = self._login("admin", "123456")
        token, cookies = self._form_context("/admin/roles", cookies)
        role = RoleRepository.get_by_code("admin")
        original_features = RoleRepository.feature_ids(role["id"])

        for values in (
            {
                "action": "update",
                "role_id": role["id"],
                "name": "被篡改角色",
                "description": "非法修改",
                "access_scope": "user",
                "enabled": "0",
            },
            {"action": "permissions", "role_id": role["id"], "feature_ids": []},
            {"action": "delete", "role_id": role["id"]},
        ):
            response = self._post_form("/admin/roles", values, token, cookies)
            self.assertEqual(response.code, 302)

        unchanged = RoleRepository.get_by_code("admin")
        self.assertEqual(unchanged["name"], role["name"])
        self.assertEqual(unchanged["access_scope"], "admin")
        self.assertTrue(unchanged["enabled"])
        self.assertEqual(RoleRepository.feature_ids(role["id"]), original_features)

    def test_task_2_3_account_dropdown_has_readable_semantics_and_css(self):
        _, cookies = self._login("admin", "123456")
        response = self.fetch(
            "/admin/", headers={"Cookie": self._cookie_header(cookies)}
        )
        self.assertEqual(response.code, 200)
        body = response.body.decode("utf-8")
        self.assertIn('<details class="admin-account-menu">', body)
        self.assertIn('class="admin-account-dropdown"', body)
        self.assertIn('aria-label="打开管理员账户菜单"', body)

        css = (PROJECT_ROOT / "app/static/css/admin-v02.css").read_text(
            encoding="utf-8"
        )
        dropdown_block = re.search(
            r"\.admin-account-dropdown\s*\{(?P<body>.*?)\}", css, re.S
        )
        self.assertIsNotNone(dropdown_block)
        self.assertRegex(dropdown_block.group("body"), r"color:\s*var\(--admin-v02-text\)")
        self.assertRegex(dropdown_block.group("body"), r"background:\s*#[0-9a-fA-F]{6}")
        self.assertIn(":focus-visible", css)
        self.assertRegex(css, r"\.admin-account-dropdown a\s*\{[^}]*min-height:\s*44px")

    def test_task2_pages_use_three_zone_layout_layui_tree_and_role_preview(self):
        _, cookies = self._login("admin", "123456")
        headers = {"Cookie": self._cookie_header(cookies)}
        for path in ("/admin/users", "/admin/roles", "/admin/features"):
            response = self.fetch(path, headers=headers)
            self.assertEqual(response.code, 200, path)
            body = response.body.decode("utf-8")
            toolbar = body.index("task2-toolbar")
            table = body.index("task2-table")
            pager = body.index("task2-pagination")
            self.assertLess(toolbar, table, path)
            self.assertLess(table, pager, path)
            self.assertRegex(body, r"每页 20 [条项]")

        roles_page = self.fetch("/admin/roles", headers=headers).body.decode("utf-8")
        self.assertIn('id="feature-tree-data"', roles_page)
        self.assertIn('data-role-feature-tree', roles_page)
        self.assertIn("js/admin-task2.js", roles_page)
        task2_js = (PROJECT_ROOT / "app/static/js/admin-task2.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('window.layui.use("tree"', task2_js)
        self.assertIn("tree.render", task2_js)
        self.assertIn("showCheckbox", task2_js)

        features_page = self.fetch("/admin/features", headers=headers).body.decode(
            "utf-8"
        )
        self.assertIn('name="parent_id"', features_page)
        self.assertIn('data-feature-level="1"', features_page)

        useradmin_role = RoleRepository.get_by_code("useradmin")
        menus_page = self.fetch(
            f"/admin/menus?preview_role_id={useradmin_role['id']}", headers=headers
        )
        self.assertEqual(menus_page.code, 200)
        menu_body = menus_page.body.decode("utf-8")
        preview = re.search(
            r'<nav aria-label="角色菜单预览">(?P<body>.*?)</nav>', menu_body, re.S
        )
        self.assertIsNotNone(preview)
        self.assertIn("用户管理", preview.group("body"))
        self.assertNotIn("角色管理", preview.group("body"))


if __name__ == "__main__":
    unittest.main()
