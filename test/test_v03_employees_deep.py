"""v0.3 数字员工与深度采集专项回归。"""

from __future__ import annotations

import asyncio
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
from app.models.deep_collection import DeepCollectionRepository
from app.models.digital_employee import DigitalEmployeeRepository
from app.models.model_engine import ModelRepository
from app.models.user import UserRepository
from app.services.deep_collection import DeepCollectionService
from app.services.digital_employee import DigitalEmployeeService

ENTRY_PATH = Path(__file__).resolve().parents[1] / "app.py"
SPEC = importlib.util.spec_from_file_location("datafinder_v03_entry", ENTRY_PATH)
ENTRY = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(ENTRY)


class V03RepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.patch = patch.object(db, "DATABASE_PATH", Path(self.temp_dir.name) / "v03.db")
        self.patch.start()
        db.init_db()
        UserRepository.ensure_admin("admin", "123456")

    def tearDown(self):
        self.patch.stop()
        self.temp_dir.cleanup()

    def _warehouse_item(self) -> int:
        with db.connection_scope() as connection:
            cursor = connection.execute(
                "INSERT INTO warehouse_items(title,url,summary,source_name) VALUES (?,?,?,?)",
                ("测试公开材料", "https://example.com/article", "摘要", "测试源"),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def test_seed_and_api_employee_crud(self):
        collector = DigitalEmployeeRepository.get_by_code("collection_specialist")
        self.assertTrue(collector["enabled"])
        self.assertTrue(collector["crawl4ai_enabled"])
        self.assertEqual(DigitalEmployeeRepository.delete(collector["id"])[0], False)
        _, initial_api_total = DigitalEmployeeRepository.list(employee_type="api", page_size=100)
        employee_id = DigitalEmployeeRepository.create(
            code="weather_api", name="天气接口", mention="气象测试",
            employee_type="api", description="读取公开天气数据",
            api_method="GET", api_url="https://example.com/weather",
            request_params={"city": "{{input}}"}, response_mode="card",
            timeout_seconds=10, enabled=True,
        )
        self.assertIsInstance(employee_id, int)
        rows, total = DigitalEmployeeRepository.list(employee_type="api", page_size=1)
        self.assertEqual(total, initial_api_total + 1)
        self.assertEqual(DigitalEmployeeRepository.get(employee_id)["mention"], "气象测试")
        self.assertTrue(DigitalEmployeeRepository.update(employee_id, description="新说明"))
        self.assertEqual(DigitalEmployeeRepository.get(employee_id)["description"], "新说明")
        self.assertTrue(DigitalEmployeeRepository.toggle(employee_id)[0])
        self.assertFalse(DigitalEmployeeRepository.get(employee_id)["enabled"])
        self.assertTrue(DigitalEmployeeRepository.delete(employee_id)[0])

    def test_deep_collection_persists_progress_logs_and_result(self):
        item_id = self._warehouse_item()
        collector = DeepCollectionService.collector_employee()
        task_ids, skipped = DeepCollectionRepository.create_tasks(
            [item_id], collector["id"], None, update=False
        )
        self.assertFalse(skipped)
        with patch.object(
            DeepCollectionService, "_fetch",
            AsyncMock(return_value=("测试标题", "这是一段足够长的真实正文内容，用于验证深度采集持久化。", {"bytes": 100})),
        ):
            asyncio.run(DeepCollectionService.run(task_ids[0]))
        detail = DeepCollectionRepository.detail(task_ids[0])
        self.assertEqual(detail["status"], "success")
        self.assertEqual(detail["progress"], 100)
        self.assertGreaterEqual(len(detail["logs"]), 6)
        result = DeepCollectionRepository.latest_result(item_id)
        self.assertIn("真实正文", result["content"])
        self.assertTrue(result["metadata"]["employee_mention"].startswith("@"))
        skipped_tasks, skipped = DeepCollectionRepository.create_tasks(
            [item_id], collector["id"], None, update=False
        )
        self.assertFalse(skipped_tasks)
        self.assertEqual(skipped, [item_id])
        update_tasks, _ = DeepCollectionRepository.create_tasks(
            [item_id], collector["id"], None, update=True
        )
        self.assertEqual(len(update_tasks), 1)

    def test_api_employee_preview_returns_real_json_shape(self):
        employee_id = DigitalEmployeeRepository.create(
            code="public_data", name="公开数据接口", mention="公开数据",
            employee_type="api", description="测试公开 JSON",
            api_method="GET", api_url="https://example.com/data",
            request_params={"q": "{{input}}"}, response_mode="card",
            timeout_seconds=10, enabled=True,
        )

        async def fake_fetch(request, raise_error=False):
            request.streaming_callback('{"city":"成都","value":28}'.encode())
            return SimpleNamespace(code=200)

        client = SimpleNamespace(fetch=fake_fetch)
        with patch(
            "app.services.digital_employee._validate_public_url", AsyncMock()
        ), patch(
            "app.services.digital_employee.guarded_fetch", fake_fetch
        ):
            result = asyncio.run(
                DigitalEmployeeService.preview(employee_id, "成都", None)
            )
        self.assertEqual(result["mode"], "card")
        self.assertEqual(result["data"]["city"], "成都")
        self.assertEqual(result["data"]["value"], 28)

    def test_llm_employee_preview_uses_configured_service_and_records_usage(self):
        model_id = ModelRepository.create(
            name="测试文本模型", model_name="test-chat", provider="Test",
            model_type="text", base_url="https://example.com/v1",
            api_key_env="", system_prompt="系统边界", enabled=True,
            is_default=True,
        )
        employee_id = DigitalEmployeeRepository.create(
            code="summary_agent", name="摘要专员", mention="摘要",
            employee_type="llm", description="生成摘要",
            use_default_model=False, model_id=model_id,
            system_prompt="只输出事实摘要", prompt_template="材料：{{input}}",
            skills=["摘要"], enabled=True,
        )
        fake_result = {
            "text": "这是模型返回的真实测试结果", "prompt_tokens": 9,
            "completion_tokens": 6, "total_tokens": 15, "latency_ms": 12,
        }
        with patch(
            "app.services.digital_employee.LLMService.complete",
            AsyncMock(return_value=fake_result),
        ):
            result = asyncio.run(
                DigitalEmployeeService.preview(employee_id, "原始材料", None)
            )
        self.assertEqual(result["mode"], "text")
        self.assertEqual(result["text"], fake_result["text"])
        self.assertEqual(ModelRepository.usage_summary(model_id)["total_tokens"], 15)


class V03WebTest(AsyncHTTPTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.patch = patch.object(db, "DATABASE_PATH", Path(self.temp_dir.name) / "v03-web.db")
        self.patch.start()
        db.init_db()
        UserRepository.ensure_admin("admin", "123456")
        with db.connection_scope() as connection:
            connection.execute(
                "INSERT INTO warehouse_items(title,url,summary,source_name) VALUES (?,?,?,?)",
                ("页面测试材料", "https://example.com/page", "仓库摘要", "测试源"),
            )
            connection.commit()
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
        page = self.fetch("/admin/login")
        cookies = self.cookies_from(page)
        token = re.search(r'name="_xsrf" value="([^"]+)"', page.body.decode()).group(1)
        response = self.fetch(
            "/admin/login", method="POST", follow_redirects=False,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": self.cookie_header(cookies)},
            body=urllib.parse.urlencode({"username": "admin", "password": "123456", "_xsrf": token}),
        )
        cookies.update(self.cookies_from(response))
        return token, cookies

    def test_pages_and_deep_task_json(self):
        token, cookies = self.login()
        headers = {"Cookie": self.cookie_header(cookies)}
        agents = self.fetch("/admin/agents", headers=headers)
        self.assertEqual(agents.code, 200, agents.body.decode("utf-8", errors="replace"))
        agent_html = agents.body.decode("utf-8")
        self.assertIn("采集专员", agent_html)
        self.assertIn("data-agent-preview", agent_html)
        warehouse = self.fetch("/admin/warehouse", headers=headers)
        self.assertEqual(warehouse.code, 200, warehouse.body.decode("utf-8", errors="replace"))
        self.assertIn("data-deep-start", warehouse.body.decode("utf-8"))
        with patch.object(DeepCollectionService, "run", AsyncMock()):
            task = self.fetch(
                "/admin/warehouse/deep-collect", method="POST",
                headers={**headers, "Content-Type": "application/json", "X-Xsrftoken": token},
                body=json.dumps({"item_ids": [1], "update": False}),
            )
        self.assertEqual(task.code, 200, task.body.decode("utf-8", errors="replace"))
        task_id = json.loads(task.body)["task_ids"][0]
        detail = self.fetch(f"/admin/warehouse/deep-tasks/{task_id}", headers=headers)
        self.assertEqual(detail.code, 200)
        self.assertEqual(json.loads(detail.body)["task"]["status"], "pending")

    def test_preview_requires_xsrf_and_available_model(self):
        token, cookies = self.login()
        headers = {"Cookie": self.cookie_header(cookies), "Content-Type": "application/json"}
        missing = self.fetch(
            "/admin/agents/preview", method="POST", headers=headers,
            body=json.dumps({"employee_id": 1, "input": "测试"}),
        )
        self.assertEqual(missing.code, 403)
        headers["X-Xsrftoken"] = token
        no_model = self.fetch(
            "/admin/agents/preview", method="POST", headers=headers,
            body=json.dumps({"employee_id": 1, "input": "测试"}),
        )
        self.assertEqual(no_model.code, 400)
        self.assertIn("模型", json.loads(no_model.body)["message"])
