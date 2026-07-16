"""认证、权限、XSRF 和核心页面的集成测试。"""

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
from app.models.rbac import FeatureRepository, RoleRepository
from app.models.user import UserRepository

ENTRY_PATH = Path(__file__).resolve().parents[1] / "app.py"
ENTRY_SPEC = importlib.util.spec_from_file_location("datafinder_entry", ENTRY_PATH)
ENTRY_MODULE = importlib.util.module_from_spec(ENTRY_SPEC)
assert ENTRY_SPEC and ENTRY_SPEC.loader
ENTRY_SPEC.loader.exec_module(ENTRY_MODULE)


class WebAppTest(AsyncHTTPTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            db,
            "DATABASE_PATH",
            Path(self.temp_dir.name) / "web-test.db",
        )
        self.db_patch.start()
        db.init_db()
        UserRepository.ensure_admin("admin", "123456")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def get_app(self):
        return ENTRY_MODULE.make_app()

    @staticmethod
    def cookies_from(response):
        result = {}
        for value in response.headers.get_list("Set-Cookie"):
            cookie = SimpleCookie()
            cookie.load(value)
            for key, morsel in cookie.items():
                result[key] = morsel.value
        return result

    def form_context(self, path, cookies=None):
        existing_cookies = dict(cookies or {})
        headers = {}
        if cookies:
            headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
        response = self.fetch(path, headers=headers)
        body = response.body.decode("utf-8")
        token_match = re.search(r'name="_xsrf" value="([^"]+)"', body)
        self.assertIsNotNone(token_match)
        response_cookies = self.cookies_from(response)
        existing_cookies.update(response_cookies)
        self.assertIn("_xsrf", existing_cookies)
        return token_match.group(1), existing_cookies

    def admin_login(self):
        token, cookies = self.form_context("/admin/login")
        response = self.post_form(
            "/admin/login",
            {"username": "admin", "password": "123456"},
            token,
            cookies,
        )
        self.assertEqual(response.code, 302)
        cookies.update(self.cookies_from(response))
        return cookies

    def post_form(self, path, values, token, cookies, follow_redirects=False):
        body = urllib.parse.urlencode({**values, "_xsrf": token})
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        return self.fetch(
            path,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": cookie_header,
            },
            body=body,
            follow_redirects=follow_redirects,
        )

    def register_and_login(self, username="student", password="123456"):
        token, cookies = self.form_context("/register")
        response = self.post_form(
            "/register",
            {"username": username, "password": password, "password_confirm": password},
            token,
            cookies,
        )
        self.assertEqual(response.code, 302)
        token, cookies = self.form_context("/")
        response = self.post_form(
            "/login",
            {"username": username, "password": password},
            token,
            cookies,
        )
        self.assertEqual(response.code, 302)
        cookies.update(self.cookies_from(response))
        return cookies

    def test_registration_login_and_user_page(self):
        cookies = self.register_and_login()
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        response = self.fetch("/index", headers={"Cookie": cookie_header})
        self.assertEqual(response.code, 200)
        self.assertIn("政务数据智能工作台".encode(), response.body)
        self.assertIn("@天气".encode(), response.body)

    def test_admin_access_control(self):
        anonymous = self.fetch("/admin/", follow_redirects=False)
        self.assertEqual(anonymous.code, 302)
        self.assertTrue(anonymous.headers["Location"].startswith("/admin/login"))

        user_cookies = self.register_and_login("ordinary", "123456")
        user_header = "; ".join(f"{key}={value}" for key, value in user_cookies.items())
        forbidden = self.fetch(
            "/admin/",
            headers={"Cookie": user_header},
            follow_redirects=False,
        )
        self.assertEqual(forbidden.code, 403)

        token, admin_cookies = self.form_context("/admin/login")
        login = self.post_form(
            "/admin/login",
            {"username": "admin", "password": "123456"},
            token,
            admin_cookies,
        )
        self.assertEqual(login.code, 302)
        admin_cookies.update(self.cookies_from(login))
        admin_header = "; ".join(
            f"{key}={value}" for key, value in admin_cookies.items()
        )
        dashboard = self.fetch("/admin/", headers={"Cookie": admin_header})
        self.assertEqual(dashboard.code, 200)
        self.assertIn("安全基线".encode(), dashboard.body)

    def test_xsrf_and_sql_injection_protection(self):
        missing_token = self.fetch(
            "/login",
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body="username=admin&password=123456",
            follow_redirects=False,
        )
        self.assertEqual(missing_token.code, 403)

        token, cookies = self.form_context("/")
        injection = self.post_form(
            "/login",
            {"username": "' OR 1=1 --", "password": "anything"},
            token,
            cookies,
        )
        self.assertEqual(injection.code, 200)
        self.assertIn("用户名或密码错误".encode(), injection.body)

    def test_management_pages_and_user_creation(self):
        admin_cookies = self.admin_login()
        admin_header = "; ".join(f"{key}={value}" for key, value in admin_cookies.items())
        for path, marker in (
            ("/admin/users", "集中维护普通用户与管理员账号"),
            ("/admin/roles", "用户与角色保持一对一关系"),
            ("/admin/features", "停用后所有角色都无法操作"),
            ("/admin/menus", "根据当前角色授权自动生成"),
        ):
            response = self.fetch(path, headers={"Cookie": admin_header})
            self.assertEqual(response.code, 200)
            self.assertIn(marker.encode(), response.body)

        user_role = RoleRepository.get_by_code("user")
        token, page_cookies = self.form_context("/admin/users", admin_cookies)
        admin_cookies.update(page_cookies)
        response = self.post_form(
            "/admin/users",
            {"action": "create", "username": "newstudent", "password": "123456", "role_id": user_role["id"]},
            token,
            admin_cookies,
        )
        self.assertEqual(response.code, 302)
        self.assertIsNotNone(UserRepository.authenticate("newstudent", "123456"))

    def test_side_isolation_and_feature_permission(self):
        admin_cookies = self.admin_login()
        header = "; ".join(f"{key}={value}" for key, value in admin_cookies.items())
        root = self.fetch("/", headers={"Cookie": header}, follow_redirects=False)
        self.assertEqual(root.code, 302)
        self.assertEqual(root.headers["Location"], "/admin/")

        feature = next(item for item in FeatureRepository.list_features() if item["code"] == "menu_management")
        FeatureRepository.set_enabled(feature["id"], False)
        forbidden = self.fetch("/admin/menus", headers={"Cookie": header}, follow_redirects=False)
        self.assertEqual(forbidden.code, 403)


if __name__ == "__main__":
    unittest.main()
