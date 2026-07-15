"""day6-2 管理页面、只读权限、采集入仓与模型 SSE 集成测试。"""

from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import urllib.parse
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import AsyncMock, patch

from tornado.testing import AsyncHTTPTestCase

from app.models import db
from app.models.model_engine import ModelRepository
from app.models.rbac import FeatureRepository, RoleRepository
from app.models.source import RuleRepository, SourceRepository
from app.models.user import UserRepository
from app.models.warehouse import WarehouseRepository


ENTRY_PATH = Path(__file__).resolve().parents[1] / "app.py"
ENTRY_SPEC = importlib.util.spec_from_file_location("datafinder_v02_entry", ENTRY_PATH)
ENTRY_MODULE = importlib.util.module_from_spec(ENTRY_SPEC)
assert ENTRY_SPEC and ENTRY_SPEC.loader
ENTRY_SPEC.loader.exec_module(ENTRY_MODULE)


class V02WebTest(AsyncHTTPTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            db, "DATABASE_PATH", Path(self.temp_dir.name) / "v02-web-test.db"
        )
        self.db_patch.start()
        db.init_db()
        UserRepository.ensure_admin("admin", "123456")

        # 自定义管理角色拥有页面查看权限，但不是默认超级管理员。
        self.assertTrue(
            RoleRepository.create("viewer", "只读管理员", "查看管理数据", "admin")
        )
        viewer_role = RoleRepository.get_by_code("viewer")
        RoleRepository.set_features(
            viewer_role["id"],
            [
                item["id"]
                for item in FeatureRepository.list_features()
                if item["route"].startswith("/admin/")
            ],
        )
        self.assertTrue(
            UserRepository.create_user("viewer", "123456", role_id=viewer_role["id"])
        )
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

    @staticmethod
    def cookie_header(cookies):
        return "; ".join(f"{key}={value}" for key, value in cookies.items())

    def form_context(self, path, cookies=None):
        existing = dict(cookies or {})
        headers = {}
        if existing:
            headers["Cookie"] = self.cookie_header(existing)
        response = self.fetch(path, headers=headers)
        self.assertEqual(response.code, 200, response.body.decode("utf-8", errors="replace"))
        body = response.body.decode("utf-8")
        token_match = re.search(r'name="_xsrf" value="([^"]+)"', body)
        self.assertIsNotNone(token_match, f"{path} 页面未输出 XSRF Token")
        existing.update(self.cookies_from(response))
        self.assertIn("_xsrf", existing)
        return token_match.group(1), existing

    def post_form(self, path, values, token, cookies, follow_redirects=False):
        body = urllib.parse.urlencode({**values, "_xsrf": token})
        return self.fetch(
            path,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "Cookie": self.cookie_header(cookies),
            },
            body=body,
            follow_redirects=follow_redirects,
        )

    def post_json(self, path, payload, token, cookies, follow_redirects=False):
        return self.fetch(
            path,
            method="POST",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json;charset=UTF-8",
                "Cookie": self.cookie_header(cookies),
                "X-Xsrftoken": token,
            },
            body=json.dumps(payload, ensure_ascii=False),
            follow_redirects=follow_redirects,
        )

    def admin_login(self, username="admin", password="123456"):
        token, cookies = self.form_context("/admin/login")
        response = self.post_form(
            "/admin/login",
            {"username": username, "password": password},
            token,
            cookies,
        )
        self.assertEqual(response.code, 302)
        cookies.update(self.cookies_from(response))
        return cookies

    def test_v02_pages_render_and_legacy_routes_redirect(self):
        cookies = self.admin_login()
        header = {"Cookie": self.cookie_header(cookies)}
        pages = (
            ("/admin/sources", "瞭源管理"),
            ("/admin/lookout", "瞭望采集"),
            ("/admin/warehouse", "数据仓库"),
            ("/admin/models", "模型引擎"),
        )
        for path, marker in pages:
            response = self.fetch(path, headers=header)
            self.assertEqual(response.code, 200, f"{path}: {response.body!r}")
            self.assertIn(marker.encode("utf-8"), response.body)

        for legacy, destination in (
            ("/admin/modules/lookout", "/admin/lookout"),
            ("/admin/modules/data", "/admin/warehouse"),
            ("/admin/modules/collect", "/admin/sources"),
            ("/admin/modules/models", "/admin/models"),
        ):
            response = self.fetch(legacy, headers=header, follow_redirects=False)
            self.assertIn(response.code, {301, 302})
            self.assertEqual(response.headers["Location"], destination)

    def test_readonly_admin_cannot_write_users_or_delete_superadmin(self):
        admin_role = RoleRepository.get_by_code("admin")
        self.assertTrue(
            UserRepository.create_user("admin1", "123456", role_id=admin_role["id"])
        )
        admin1 = UserRepository.get_user_by_username("admin1")

        viewer_cookies = self.admin_login("viewer", "123456")
        readonly_page = self.fetch(
            "/admin/users",
            headers={"Cookie": self.cookie_header(viewer_cookies)},
        )
        self.assertEqual(readonly_page.code, 200)
        self.assertIn("只读".encode(), readonly_page.body)
        # 业务模块按 role_feature 授权，非超级管理员可以维护瞭源。
        token, viewer_cookies = self.form_context("/admin/sources", viewer_cookies)
        source_created = self.post_form(
            "/admin/sources",
            {
                "action": "create_source",
                "name": "只读角色业务测试源",
                "code": "viewer_business_source",
                "base_url": "https://example.com/search",
                "description": "验证业务权限与权限配置权限分离",
                "headers_json": "{}",
                "enabled": "1",
            },
            token,
            viewer_cookies,
        )
        self.assertEqual(source_created.code, 302)
        sources, _ = SourceRepository.list(keyword="viewer_business_source")
        self.assertEqual(len(sources), 1)

        # 用户、角色、功能、菜单属于超级管理员独占的权限配置。即使攻击者
        # 拥有相应 role_feature 并构造合法 XSRF POST，服务端仍必须拒绝。
        forbidden = self.post_form(
            "/admin/users",
            {"action": "delete", "user_id": admin1["id"]},
            token,
            viewer_cookies,
        )
        self.assertEqual(forbidden.code, 403)
        self.assertIsNotNone(UserRepository.get_user_by_username("admin1"))
        for path in ("/admin/roles", "/admin/features", "/admin/menus"):
            response = self.post_form(
                path,
                {"action": "create"},
                token,
                viewer_cookies,
            )
            self.assertEqual(response.code, 403, path)

        admin_cookies = self.admin_login()
        token, admin_cookies = self.form_context("/admin/users", admin_cookies)
        superadmin = UserRepository.get_user_by_username("admin")
        protected = self.post_form(
            "/admin/users",
            {"action": "delete", "user_id": superadmin["id"]},
            token,
            admin_cookies,
        )
        self.assertEqual(protected.code, 302)
        self.assertIsNotNone(UserRepository.get_user_by_username("admin"))

    def test_mock_collection_and_warehouse_import(self):
        cookies = self.admin_login()
        token, cookies = self.form_context("/admin/lookout", cookies)
        rules, _ = RuleRepository.list(enabled_only=True, page=1, page_size=200)
        rule = next(item for item in rules if item["parser_type"] == "baidu_news")
        fixture = [
            {
                "title": "四川公开新闻一",
                "url": "https://news.example.com/mock/1",
                "summary": "固定模拟摘要一",
                "source_name": "百度新闻测试夹具",
                "published_at": "2026-07-13",
            },
            {
                "title": "四川公开新闻二",
                "url": "https://news.example.com/mock/2",
                "summary": "固定模拟摘要二",
                "source_name": "百度新闻测试夹具",
                "published_at": "2026-07-13",
            },
        ]
        collector_mock = AsyncMock(return_value=fixture)
        with patch(
            "app.controllers.lookout.CollectorService.collect", collector_mock
        ):
            response = self.post_form(
                "/admin/lookout/collect",
                {
                    "keyword": "四川",
                    "rule_id": rule["id"],
                    "page": 1,
                    "page_size": 12,
                },
                token,
                cookies,
            )
        self.assertEqual(response.code, 200, response.body.decode("utf-8", errors="replace"))
        payload = json.loads(response.body)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["items"]), 2)
        collector_mock.assert_awaited_once()

        result_ids = [item["id"] for item in payload["items"]]
        imported = self.post_json(
            "/admin/warehouse/import", {"result_ids": result_ids}, token, cookies
        )
        self.assertEqual(imported.code, 200, imported.body.decode("utf-8", errors="replace"))
        imported_payload = json.loads(imported.body)
        self.assertEqual(imported_payload["inserted"], 2)

        repeated = self.post_json(
            "/admin/warehouse/import", {"result_ids": result_ids}, token, cookies
        )
        repeated_payload = json.loads(repeated.body)
        self.assertEqual((repeated_payload["inserted"], repeated_payload["skipped"]), (0, 2))

        items, total = WarehouseRepository.list(keyword="四川")
        self.assertEqual(total, 2)
        self.assertEqual(len(items), 2)

    def test_model_category_page_and_mock_sse_usage(self):
        admin = UserRepository.get_user_by_username("admin")
        text_id = ModelRepository.create(
            name="问数文本模型",
            model_name="mock-text",
            model_type="text",
            provider="OpenAI Compatible",
            base_url="https://models.example.com/v1",
            api_key_env="",
            is_default=True,
            created_by=admin["id"],
        )
        ModelRepository.create(
            name="图像模型",
            model_name="mock-image",
            model_type="image",
            provider="OpenAI Compatible",
            base_url="https://models.example.com/v1",
            api_key_env="",
            created_by=admin["id"],
        )

        cookies = self.admin_login()
        header = {"Cookie": self.cookie_header(cookies)}
        filtered = self.fetch("/admin/models?type=image", headers=header)
        self.assertEqual(filtered.code, 200, filtered.body.decode("utf-8", errors="replace"))
        self.assertIn("图像模型".encode(), filtered.body)
        self.assertNotIn("问数文本模型".encode(), filtered.body)

        token, cookies = self.form_context("/admin/models", cookies)
        llm_result = {
            "text": "这是模拟模型回答。",
            "prompt_tokens": 5,
            "completion_tokens": 3,
            "total_tokens": 8,
            "latency_ms": 12,
        }
        llm_mock = AsyncMock(return_value=llm_result)
        with patch("app.controllers.model_engine.LLMService.complete", llm_mock):
            response = self.post_json(
                "/admin/models/chat",
                {"model_id": text_id, "message": "测试问题"},
                token,
                cookies,
            )
        self.assertEqual(response.code, 200, response.body.decode("utf-8", errors="replace"))
        self.assertTrue(response.headers["Content-Type"].startswith("text/event-stream"))
        body = response.body.decode("utf-8")
        self.assertIn("event: delta", body)
        self.assertIn("这是模拟模型回答", body)
        self.assertIn("event: usage", body)
        self.assertIn('"total_tokens": 8', body)
        self.assertIn("event: done", body)
        llm_mock.assert_awaited_once()

        summary = ModelRepository.usage_summary(text_id)
        self.assertEqual(summary["usage_count"], 1)
        self.assertEqual(summary["total_tokens"], 8)


if __name__ == "__main__":
    unittest.main()
