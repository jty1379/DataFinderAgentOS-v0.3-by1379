"""v0.3 Crawl4AI、天气员工、会话持久化与用户工作台回归。"""

from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import unittest
import urllib.parse
from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tornado.testing import AsyncHTTPTestCase

from app.models import db
from app.models.conversation import ConversationRepository
from app.models.digital_employee import DigitalEmployeeRepository
from app.models.user import UserRepository
from app.services.deep_collection import DeepCollectionService
from app.services.digital_employee import DigitalEmployeeService

ENTRY_PATH = Path(__file__).resolve().parents[1] / "app.py"
SPEC = importlib.util.spec_from_file_location("datafinder_v03_workspace_entry", ENTRY_PATH)
ENTRY = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(ENTRY)


class V03WorkspaceRepositoryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.patch = patch.object(db, "DATABASE_PATH", Path(self.temp_dir.name) / "v03-workspace.db")
        self.patch.start()
        db.init_db()
        UserRepository.create_user("student", "123456")

    def tearDown(self):
        self.patch.stop()
        self.temp_dir.cleanup()

    def test_weather_seed_and_conversation_persistence(self):
        weather = DigitalEmployeeRepository.get_by_code("weather")
        self.assertEqual(weather["mention"], "天气")
        self.assertIn("wttr.in", weather["api_url"])
        user = UserRepository.get_user_by_username("student")
        conversation_id = ConversationRepository.create(
            user["id"], ConversationRepository.title_from_prompt("@天气 成都"),
            employee_id=weather["id"],
        )
        ConversationRepository.add_message(conversation_id, "user", "@天气 成都")
        ConversationRepository.add_message(
            conversation_id, "assistant", '{"kind":"weather"}', "card", {"source": "wttr.in"}
        )
        self.assertEqual(ConversationRepository.list_for_user(user["id"])[0]["message_count"], 2)
        self.assertEqual(ConversationRepository.messages(conversation_id, user["id"])[1]["metadata"]["source"], "wttr.in")

    async def test_weather_url_encoding_and_card_normalization(self):
        weather = DigitalEmployeeRepository.get_by_code("weather")
        captured = {}
        payload = {
            "current_condition": [{
                "temp_C": "28", "FeelsLikeC": "30", "humidity": "66",
                "windspeedKmph": "8", "winddir16Point": "NE", "visibility": "10",
                "pressure": "1002", "weatherDesc": [{"value": "Cloudy"}],
            }],
            "nearest_area": [{"areaName": [{"value": "Chengdu"}], "region": [{"value": "Sichuan"}], "country": [{"value": "China"}]}],
            "weather": [{"date": "2026-07-14", "mintempC": "24", "maxtempC": "33", "hourly": [{"weatherDesc": [{"value": "Cloudy"}]}]}],
        }

        async def fake_fetch(request, raise_error=False):
            captured["url"] = request.url
            request.streaming_callback(json.dumps(payload).encode())
            return SimpleNamespace(code=200)

        client = SimpleNamespace(fetch=fake_fetch)
        with patch("app.services.digital_employee._validate_public_url", AsyncMock()), patch(
            "app.services.digital_employee.guarded_fetch", fake_fetch
        ):
            result = await DigitalEmployeeService.preview(weather["id"], "成都", None)
        self.assertIn("%E6%88%90%E9%83%BD", captured["url"])
        self.assertEqual(result["data"]["kind"], "weather")
        self.assertEqual(result["data"]["location"], "成都")
        self.assertEqual(result["data"]["temperature_c"], "28")

    async def test_deep_fetch_calls_crawl4ai_and_returns_markdown(self):
        markdown = SimpleNamespace(fit_markdown="# 测试标题\n\n这是 Crawl4AI 提取的详细正文内容。")
        result = SimpleNamespace(
            success=True, markdown=markdown, metadata={"title": "测试标题"},
            links={"internal": [{"href": "/a"}], "external": []},
            redirected_url="", url="https://example.com/page", status_code=200,
        )

        class FakeCrawler:
            def __init__(self, config): self.config = config
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return None
            async def arun(self, url, config):
                self.url, self.run_config = url, config
                return result

        with patch("app.services.deep_collection._validate_public_url", AsyncMock()), patch(
            "app.services.deep_collection.AsyncWebCrawler", FakeCrawler
        ):
            title, content, metadata = await DeepCollectionService._fetch("https://example.com/page")
        self.assertEqual(title, "测试标题")
        self.assertIn("详细正文", content)
        self.assertEqual(metadata["parser"], "crawl4ai")


class V03WorkspaceWebTest(AsyncHTTPTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.patch = patch.object(db, "DATABASE_PATH", Path(self.temp_dir.name) / "v03-workspace-web.db")
        self.patch.start()
        db.init_db()
        UserRepository.create_user("student", "123456")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.patch.stop()
        self.temp_dir.cleanup()

    def get_app(self):
        return ENTRY.make_app()

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

    def login(self):
        page = self.fetch("/")
        cookies = self.cookies_from(page)
        token = re.search(r'name="_xsrf" value="([^"]+)"', page.body.decode()).group(1)
        response = self.fetch(
            "/login", method="POST", follow_redirects=False,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": self.cookie_header(cookies)},
            body=urllib.parse.urlencode({"username": "student", "password": "123456", "_xsrf": token}),
        )
        cookies.update(self.cookies_from(response))
        return token, cookies

    def test_user_workspace_and_weather_chat_flow(self):
        token, cookies = self.login()
        headers = {"Cookie": self.cookie_header(cookies)}
        page = self.fetch("/index", headers=headers)
        html = page.body.decode()
        self.assertIn("当前模型服务", html)
        self.assertIn("任务记录", html)
        self.assertIn("@天气", html)
        weather = DigitalEmployeeRepository.get_by_code("weather")
        fake_result = {
            "mode": "card", "employee": "天气专员", "mention": "@天气",
            "data": {"kind": "weather", "location": "成都", "temperature_c": "28", "forecast": []},
        }
        with patch.object(DigitalEmployeeService, "preview", AsyncMock(return_value=fake_result)):
            response = self.fetch(
                "/api/chat", method="POST",
                headers={**headers, "Content-Type": "application/json", "X-Xsrftoken": token},
                body=json.dumps({"message": "@天气 成都", "employee_id": weather["id"]}),
            )
        data = json.loads(response.body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["message"]["content_type"], "card")
        detail = self.fetch(f"/api/conversations/{data['conversation']['id']}", headers=headers)
        messages = json.loads(detail.body)["messages"]
        self.assertEqual([item["role"] for item in messages], ["user", "assistant"])

    def test_user_chat_requires_xsrf(self):
        _, cookies = self.login()
        response = self.fetch(
            "/api/chat", method="POST",
            headers={"Cookie": self.cookie_header(cookies), "Content-Type": "application/json"},
            body=json.dumps({"message": "测试"}),
        )
        self.assertEqual(response.code, 403)
