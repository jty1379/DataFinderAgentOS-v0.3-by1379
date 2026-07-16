"""成员 D 真实统计、生物识别档案和手势冷却验收。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import db
from app.models.biometrics import BiometricRepository
from app.models.dashboard import DashboardRepository
from app.models.user import UserRepository


class MemberDRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DATABASE_PATH", Path(self.temp_dir.name) / "member-d.db")
        self.db_patch.start()
        db.init_db()
        UserRepository.create_user("memberd", "123456")
        self.user = UserRepository.get_user_by_username("memberd")

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_dashboard_uses_database_and_creates_traceable_alert(self):
        with db.connection_scope() as connection:
            conversation = connection.execute(
                "INSERT INTO user_conversations(user_id,title) VALUES (?,?)",
                (self.user["id"], "风险复核"),
            ).lastrowid
            connection.execute(
                "INSERT INTO user_messages(conversation_id,role,content) VALUES (?,?,?)",
                (conversation, "user", "请核查数据泄露风险并保留证据"),
            )
            connection.execute(
                """INSERT INTO collection_runs(user_id,keyword,status,result_count)
                   VALUES (?,?,?,?)""",
                (self.user["id"], "成都", "success", 3),
            )
            connection.execute(
                """INSERT INTO collection_results(run_id,title,url,source_name)
                   VALUES (1,'政务动态','https://example.com/1','政务公开')"""
            )
            connection.commit()
        dashboard = DashboardRepository.overview()
        self.assertEqual(dashboard["metrics"]["today_conversations"], 1)
        self.assertEqual(dashboard["metrics"]["today_collection"], 1)
        self.assertEqual(dashboard["metrics"]["collection_success_rate"], 100)
        self.assertEqual(dashboard["metrics"]["high_risk_alerts"], 1)
        opinion = DashboardRepository.opinion()
        self.assertEqual(opinion["summary"]["total"], 1)
        self.assertEqual(opinion["alerts"][0]["source_type"], "user_message")

    def test_face_profile_global_switch_and_gesture_cooldown(self):
        embedding = json.dumps([0.1] * 255)
        BiometricRepository.save_face_profile(self.user["id"], embedding, 6)
        profile = BiometricRepository.face_profile(self.user["id"])
        self.assertEqual(profile["sample_count"], 6)
        admin = UserRepository.get_superadmin()
        BiometricRepository.set_face_login_enabled(False, admin["id"])
        self.assertFalse(BiometricRepository.face_login_enabled())
        BiometricRepository.set_face_login_enabled(True, admin["id"])
        self.assertTrue(BiometricRepository.log_gesture(self.user["id"], "victory", "weather", 0.9))
        self.assertFalse(BiometricRepository.log_gesture(self.user["id"], "victory", "weather", 0.9))
        self.assertTrue(BiometricRepository.toggle_user_face(self.user["id"], False))
        self.assertFalse(BiometricRepository.face_profile(self.user["id"])["enabled"])
        self.assertTrue(BiometricRepository.delete_face_profile(self.user["id"]))


if __name__ == "__main__":
    unittest.main()
