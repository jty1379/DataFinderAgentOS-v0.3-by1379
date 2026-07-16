"""A 组剩余平台治理能力的持久化与 HTTP 回归测试。"""

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
from app.models.conversation import ConversationRepository
from app.models.opinion import AuditLogRepository, OpinionAlertRepository, SensitiveWordRepository
from app.models.user import UserRepository
from app.services.opinion import OpinionSecurityService
from app.services.security import AuditLogService
from app.services.system_settings import SystemSettingsService

ENTRY_PATH = Path(__file__).resolve().parents[1] / "app.py"
ENTRY_SPEC = importlib.util.spec_from_file_location("datafinder_a_entry", ENTRY_PATH)
ENTRY_MODULE = importlib.util.module_from_spec(ENTRY_SPEC)
assert ENTRY_SPEC and ENTRY_SPEC.loader
ENTRY_SPEC.loader.exec_module(ENTRY_MODULE)


class APlatformRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.patch = patch.object(db, "DATABASE_PATH", Path(self.temp_dir.name) / "a.db")
        self.patch.start()
        db.init_db()
        UserRepository.ensure_admin("admin", "123456")
        self.assertTrue(UserRepository.create_user("a_user", "123456"))
        self.user = UserRepository.get_user_by_username("a_user")

    def tearDown(self):
        self.patch.stop()
        self.temp_dir.cleanup()

    def test_session_true_total_filters_metrics_and_lifecycle(self):
        ids = []
        for index in range(25):
            conversation_id = ConversationRepository.create(self.user["id"], f"测试会话 {index:02d}")
            message_id = ConversationRepository.add_message(
                conversation_id, "user", f"内容 {index}", metadata={"usage": {"total_tokens": index, "latency_ms": index * 10}}
            )
            if index == 24:
                ConversationRepository.update_message_security(
                    message_id, {"risk_level": "high", "matched_words": [{"word": "测试"}]}
                )
            ids.append(conversation_id)

        rows, total = ConversationRepository.admin_list(page=1, page_size=20)
        self.assertEqual(total, 25)
        self.assertEqual(len(rows), 20)
        filtered, filtered_total = ConversationRepository.admin_list(keyword="24")
        self.assertEqual(filtered_total, 1)
        self.assertEqual(filtered[0]["risk_level"], "high")
        self.assertEqual(filtered[0]["total_tokens"], 24)
        self.assertEqual(filtered[0]["max_latency_ms"], 240)

        self.assertEqual(ConversationRepository.set_archived(ids[:2], True), 2)
        archived, archived_total = ConversationRepository.admin_list(status="archived")
        self.assertEqual(archived_total, 2)
        self.assertTrue(all(item["status"] == "archived" for item in archived))
        self.assertEqual(ConversationRepository.batch_delete_for_admin(ids[:2]), 2)

    def test_settings_validate_types_ranges_and_known_keys(self):
        self.assertEqual(SystemSettingsService.validate("allow_register", "ON"), "true")
        self.assertEqual(SystemSettingsService.validate("default_collect_timeout", "45"), "45")
        with self.assertRaises(ValueError):
            SystemSettingsService.validate("default_collect_timeout", "999")
        with self.assertRaises(ValueError):
            SystemSettingsService.validate("unknown_setting", "x")
        self.assertTrue(SystemSettingsService.update_setting("allow_register", "false"))
        self.assertFalse(SystemSettingsService.allow_register())

    def test_opinion_analysis_is_persistent_and_deduplicated(self):
        self.assertTrue(SensitiveWordRepository.create("重大泄露", "security", 4, "测试"))
        self.assertTrue(SystemSettingsService.update_setting("sensitive_word_threshold", "1"))
        first = OpinionSecurityService.analyze_and_record(
            "chat", 99, "发生重大泄露，请立即处理", self.user["id"], {"case": "a"}
        )
        second = OpinionSecurityService.analyze_and_record(
            "chat", 99, "发生重大泄露，请立即处理", self.user["id"], {"case": "a"}
        )
        self.assertEqual(first["risk_level"], "critical")
        self.assertGreater(first["alert_id"], 0)
        self.assertEqual(first["alert_id"], second["alert_id"])
        alerts, pager = OpinionAlertRepository.list_alerts()
        self.assertEqual(pager["total"], 1)
        self.assertEqual(alerts[0]["content_hash"], alerts[0]["content_hash"].lower())

    def test_audit_filters_resource_and_date(self):
        self.assertTrue(
            AuditLogRepository.create("update", "setting", 2, self.user["id"], "a_user", "127.0.0.1")
        )
        logs, pager = AuditLogRepository.list_logs(resource_type="setting", resource_id=2)
        self.assertEqual(pager["total"], 1)
        self.assertEqual(logs[0]["user_name"], "a_user")
        with patch("app.services.security.AuditLogRepository.create", return_value=False):
            with self.assertLogs("app", level="ERROR") as captured:
                self.assertFalse(AuditLogService.log_action("update", "setting", 2))
        self.assertTrue(any("审计日志写入失败" in line for line in captured.output))


class APlatformHttpTest(AsyncHTTPTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.patch = patch.object(db, "DATABASE_PATH", Path(self.temp_dir.name) / "a-http.db")
        self.patch.start()
        db.init_db()
        UserRepository.ensure_admin("admin", "123456")
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.patch.stop()
        self.temp_dir.cleanup()

    def get_app(self):
        return ENTRY_MODULE.make_app()

    @staticmethod
    def _cookies(response):
        output = {}
        for value in response.headers.get_list("Set-Cookie"):
            cookie = SimpleCookie()
            cookie.load(value)
            output.update({key: morsel.value for key, morsel in cookie.items()})
        return output

    @staticmethod
    def _header(cookies):
        return "; ".join(f"{key}={value}" for key, value in cookies.items())

    def _context(self, path, cookies=None):
        cookies = dict(cookies or {})
        response = self.fetch(path, headers={"Cookie": self._header(cookies)} if cookies else {})
        cookies.update(self._cookies(response))
        token = re.search(r'name="_xsrf" value="([^"]+)"', response.body.decode("utf-8"))
        self.assertIsNotNone(token)
        return token.group(1), cookies

    def _post(self, path, values, token, cookies):
        return self.fetch(
            path, method="POST", follow_redirects=False,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": self._header(cookies)},
            body=urllib.parse.urlencode({**values, "_xsrf": token}),
        )

    def _admin(self):
        token, cookies = self._context("/admin/login")
        response = self._post("/admin/login", {"username": "admin", "password": "123456"}, token, cookies)
        cookies.update(self._cookies(response))
        return cookies

    def test_registration_setting_session_pages_and_audit(self):
        SystemSettingsService.update_setting("allow_register", "false")
        self.assertEqual(self.fetch("/register").code, 403)
        SystemSettingsService.update_setting("allow_register", "true")
        cookies = self._admin()
        token, cookies = self._context("/admin/settings", cookies)
        response = self._post(
            "/admin/settings",
            {"action": "update", "setting_key": "screen_refresh_interval", "setting_value": "15"},
            token, cookies,
        )
        self.assertEqual(response.code, 302)
        token, cookies = self._context("/admin/settings", cookies)
        response = self._post(
            "/admin/settings",
            {
                "action": "batch_update",
                "setting_system_name": "智能瞭望与智能问数系统",
                "setting_system_logo": "",
                "setting_system_description": "平台治理回归",
                "setting_home_announcement": "",
                "setting_default_model": "",
                "setting_allow_register": "true",
                "setting_sensitive_word_threshold": "5",
                "setting_screen_refresh_interval": "20",
                "setting_default_collect_timeout": "40",
                "setting_max_collect_count": "80",
                "setting_max_upload_size": "10485760",
                "setting_session_timeout_minutes": "1440",
                "setting_session_inactivity_timeout_minutes": "30",
            },
            token,
            cookies,
        )
        self.assertEqual(response.code, 302)
        self.assertEqual(SystemSettingsService.get_integer("screen_refresh_interval"), 20)
        self.assertFalse(SystemSettingsService.get_boolean("enable_face_login"))
        session_page = self.fetch("/admin/sessions", headers={"Cookie": self._header(cookies)})
        self.assertEqual(session_page.code, 200)
        self.assertIn("会话管理", session_page.body.decode("utf-8"))
        audit_page = self.fetch("/admin/audit/logs?resource_type=setting", headers={"Cookie": self._header(cookies)})
        self.assertEqual(audit_page.code, 200, audit_page.body.decode("utf-8", errors="replace"))
        self.assertIn("系统设置单项更新", audit_page.body.decode("utf-8"))
        SystemSettingsService.update_setting("maintenance_mode", "true")
        self.assertEqual(self.fetch("/index").code, 503)
        SystemSettingsService.update_setting("maintenance_mode", "false")


if __name__ == "__main__":
    unittest.main()
