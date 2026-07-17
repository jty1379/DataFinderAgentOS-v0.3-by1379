"""Member B runtime closure tests for interfaces, Skills, TTS and multimodal tasks."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models import db
from app.models.digital_employee import DigitalEmployeeRepository
from app.models.interface import InterfaceCallRepository, InterfaceRepository
from app.models.model_engine import ModelRepository
from app.models.multimodal import MultimodalConfigRepository, MultimodalTaskRepository
from app.models.skill import EmployeeSkillRepository, SkillRepository
from app.models.tts import TTSCallRepository, TTSConfigRepository
from app.services.digital_employee import DigitalEmployeeError, DigitalEmployeeService
from app.services.multimodal import MultimodalService
from app.services.tts import TTSService


class TestAIRuntimeClosure(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            db, "DATABASE_PATH", Path(self.temp_dir.name) / "ai-closure.db"
        )
        self.db_patch.start()
        db.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_bound_interface_drives_employee_and_records_call(self):
        interface_id = InterfaceRepository.create(
            code="managed_data",
            name="托管数据接口",
            api_url="https://example.com/data",
            request_method="GET",
            request_params={"q": "{{input}}"},
            response_path="data",
            timeout_seconds=8,
            retry_count=0,
            enabled=True,
        )
        employee_id = DigitalEmployeeRepository.create(
            code="managed_agent",
            name="托管接口员工",
            mention="托管员工",
            employee_type="api",
            interface_id=interface_id,
            response_mode="card",
            enabled=True,
        )

        async def fake_fetch(request, raise_error=False):
            request.streaming_callback(json.dumps({"data": {"value": 28}}).encode())
            return SimpleNamespace(code=200)

        with (
            patch("app.services.digital_employee._validate_public_url", AsyncMock()),
            patch(
                "app.services.digital_employee.guarded_fetch",
                fake_fetch,
            ),
        ):
            result = asyncio.run(DigitalEmployeeService.execute(employee_id, "成都", None))

        self.assertEqual(result["data"], {"value": 28})
        calls, total = InterfaceCallRepository.list(interface_id)
        self.assertEqual(total, 1)
        self.assertTrue(calls[0]["success"])

        InterfaceRepository.toggle(interface_id)
        with self.assertRaisesRegex(DigitalEmployeeError, "接口已停用"):
            asyncio.run(DigitalEmployeeService.execute(employee_id, "成都", None))

    def test_prompt_skill_changes_llm_and_tool_skill_queries_database(self):
        model_id = ModelRepository.create(
            name="技能测试模型",
            model_name="skill-test",
            provider="Test",
            model_type="text",
            base_url="https://example.com/v1",
            api_key_env="",
            system_prompt="模型基础提示",
            enabled=True,
            is_default=True,
        )
        employee_id = DigitalEmployeeRepository.create(
            code="skill_agent",
            name="技能员工",
            mention="技能员工",
            employee_type="llm",
            model_id=model_id,
            use_default_model=False,
            system_prompt="员工提示",
            prompt_template="{{input}}",
            enabled=True,
        )
        prompt_skill = SkillRepository.create(
            code="strict_summary",
            name="严格摘要技能",
            system_prompt="只输出有来源的事实",
            tools={},
            triggers={},
            enabled=True,
        )
        EmployeeSkillRepository.bind(employee_id, prompt_skill)
        captured = {}

        async def fake_complete(model, prompt):
            captured["system_prompt"] = model["system_prompt"]
            return {
                "text": "事实摘要",
                "prompt_tokens": 2,
                "completion_tokens": 2,
                "total_tokens": 4,
                "latency_ms": 3,
            }

        with patch(
            "app.services.digital_employee.LLMService.complete", side_effect=fake_complete
        ):
            result = asyncio.run(DigitalEmployeeService.execute(employee_id, "材料", None))
        self.assertIn("只输出有来源的事实", captured["system_prompt"])
        self.assertEqual(result["skills_used"], ["strict_summary"])

        analyst = DigitalEmployeeRepository.get_by_code("analyst")
        query_result = asyncio.run(
            DigitalEmployeeService.execute(analyst["id"], "各来源分别有多少条新闻？", None)
        )
        self.assertEqual(query_result["mode"], "card")
        self.assertEqual(query_result["data"]["intent"], "sources_breakdown")
        self.assertIn("database_query", query_result["skills_used"])
        with self.assertRaisesRegex(DigitalEmployeeError, "安全策略拒绝"):
            asyncio.run(
                DigitalEmployeeService.execute(analyst["id"], "drop table users", None)
            )
        with db.connection_scope() as connection:
            latest = connection.execute(
                """SELECT success FROM employee_call_logs
                   WHERE employee_id=? ORDER BY id DESC LIMIT 1""",
                (analyst["id"],),
            ).fetchone()
        self.assertFalse(bool(latest["success"]))

    def test_tts_uses_database_config_and_records_cache(self):
        TTSConfigRepository.update_config(
            enabled=True,
            provider="local",
            default_voice="zh_female",
            rate=20,
            volume=10,
            pitch=0,
        )
        cache_path = str(Path(self.temp_dir.name) / "speech.mp3")
        with (
            patch("app.services.tts._cache_path", return_value=cache_path),
            patch.object(TTSService, "_synthesize_chunk", AsyncMock(return_value=b"audio")),
        ):
            first = asyncio.run(TTSService.synthesize("数据库配置测试"))
            second = asyncio.run(TTSService.synthesize("数据库配置测试"))
        self.assertEqual(TTSService.get_config()["rate"], 20)
        self.assertFalse(first["from_cache"])
        self.assertTrue(second["from_cache"])
        stats = TTSCallRepository.stats()
        self.assertEqual(stats["total_calls"], 2)
        self.assertEqual(stats["cached_calls"], 1)

    def test_multimodal_image_is_async_database_task_and_video_fails_honestly(self):
        MultimodalConfigRepository.update_config(
            {
                "enabled": True,
                "provider": "openai_compatible",
                "api_key_env": "TEST_MM_KEY",
                "base_url": "https://images.example.com/v1",
                "image_model": "real-image-model",
                "default_image_size": "1024x1024",
            }
        )
        with patch.object(MultimodalService, "schedule"):
            image_task = MultimodalService.submit("image", "成都城市天际线")

        async def fake_fetch(request, raise_error=False):
            request.streaming_callback(
                json.dumps(
                    {"id": "provider-1", "data": [{"url": "https://cdn.example.com/1.png"}]}
                ).encode()
            )
            return SimpleNamespace(code=200)

        with (
            patch.dict(os.environ, {"TEST_MM_KEY": "secret-value"}),
            patch("app.services.multimodal._validate_public_url", AsyncMock()),
            patch(
                "app.services.multimodal.guarded_fetch",
                fake_fetch,
            ),
        ):
            completed = asyncio.run(MultimodalService.run(image_task["task_id"]))
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["provider_task_id"], "provider-1")
        self.assertEqual(completed["resource_url"], "https://cdn.example.com/1.png")

        with patch.object(MultimodalService, "schedule"):
            video_task = MultimodalService.submit("video", "视频能力检查")
        failed = asyncio.run(MultimodalService.run(video_task["task_id"]))
        self.assertEqual(failed["status"], "failed")
        self.assertIn("未配置/不可用", failed["error_message"])
        self.assertEqual(MultimodalTaskRepository.stats()["total_calls"], 2)

    def test_minimax_tts_and_image_generation_protocols(self):
        captured = {}

        async def fake_tts_fetch(request, raise_error=False):
            del raise_error
            captured["tts_url"] = request.url
            captured["tts_payload"] = json.loads(request.body)
            request.streaming_callback(
                json.dumps(
                    {
                        "data": {"audio": b"ID3-audio".hex(), "status": 2},
                        "base_resp": {"status_code": 0, "status_msg": "success"},
                    }
                ).encode()
            )
            return SimpleNamespace(code=200)

        tts_config = {
            "provider": "minimax",
            "api_key_env": "TEST_MINIMAX_KEY",
            "base_url": "https://api.minimaxi.com/v1",
            "rate": 0,
            "volume": 0,
            "pitch": 0,
        }
        with (
            patch.dict(os.environ, {"TEST_MINIMAX_KEY": "secret-value"}),
            patch(
                "app.services.tts.guarded_fetch",
                fake_tts_fetch,
            ),
        ):
            audio = asyncio.run(
                TTSService._minimax_tts("协议测试", "male-qn-qingse", tts_config)
            )
        self.assertEqual(audio, b"ID3-audio")
        self.assertEqual(captured["tts_url"], "https://api.minimaxi.com/v1/t2a_v2")
        self.assertEqual(captured["tts_payload"]["model"], "speech-2.8-hd")

        MultimodalConfigRepository.update_config(
            {
                "enabled": True,
                "provider": "minimax",
                "api_key_env": "TEST_MINIMAX_KEY",
                "base_url": "https://api.minimaxi.com/v1",
                "image_model": "image-01",
                "default_image_size": "1024x1024",
            }
        )
        with patch.object(MultimodalService, "schedule"):
            image_task = MultimodalService.submit("image", "蓝色政务数据图标")

        async def fake_image_fetch(request, raise_error=False):
            del raise_error
            captured["image_url"] = request.url
            captured["image_payload"] = json.loads(request.body)
            request.streaming_callback(
                json.dumps(
                    {
                        "id": "minimax-image-1",
                        "data": {"image_urls": ["https://cdn.example.com/minimax.png"]},
                        "base_resp": {"status_code": 0, "status_msg": "success"},
                    }
                ).encode()
            )
            return SimpleNamespace(code=200)

        with (
            patch.dict(os.environ, {"TEST_MINIMAX_KEY": "secret-value"}),
            patch("app.services.multimodal._validate_public_url", AsyncMock()),
            patch(
                "app.services.multimodal.guarded_fetch",
                fake_image_fetch,
            ),
        ):
            completed = asyncio.run(MultimodalService.run(image_task["task_id"]))
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(captured["image_url"], "https://api.minimaxi.com/v1/image_generation")
        self.assertEqual(captured["image_payload"]["model"], "image-01")
        self.assertEqual(completed["resource_url"], "https://cdn.example.com/minimax.png")

    def test_secret_fields_accept_environment_names_only(self):
        with self.assertRaises(ValueError):
            TTSConfigRepository.update_config(
                enabled=True, provider="local", api_key_env="sk-real-secret"
            )
        with self.assertRaises(ValueError):
            MultimodalConfigRepository.update_config(
                {"api_key_env": "actual-secret", "provider": "openai_compatible"}
            )


if __name__ == "__main__":
    unittest.main()
