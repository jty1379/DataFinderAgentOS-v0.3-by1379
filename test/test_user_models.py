"""Repository 的基础单元测试。"""

from __future__ import annotations

import tempfile
import sqlite3
from contextlib import closing
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import db, user
from app.models.rbac import FeatureRepository, MenuRepository, RoleRepository


class UserRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db_patch = patch.object(db, "DATABASE_PATH", self.db_path)
        self.db_patch.start()
        db.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_create_and_authenticate(self):
        self.assertTrue(user.UserRepository.create_user("tester", "123456"))
        self.assertFalse(user.UserRepository.create_user("tester", "654321"))
        with db.connection_scope() as connection:
            stored = connection.execute(
                "SELECT password_hash, salt FROM users WHERE username = ?",
                ("tester",),
            ).fetchone()
        self.assertNotEqual(stored["password_hash"], "123456")
        self.assertEqual(len(stored["password_hash"]), 64)
        self.assertEqual(len(stored["salt"]), 32)
        result = user.UserRepository.authenticate("tester", "123456")
        self.assertIsNotNone(result)
        self.assertEqual(result["role"], "user")
        self.assertIsNone(user.UserRepository.authenticate("tester", "wrong"))

    def test_admin_seed_does_not_reset_existing_account(self):
        seeded = user.UserRepository.authenticate("admin", "123456")
        self.assertIsNotNone(seeded)
        self.assertTrue(
            user.UserRepository.change_superadmin_password(
                seeded["id"], "123456", "changed"
            )
        )
        self.assertFalse(user.UserRepository.ensure_admin("admin", "123456"))
        self.assertIsNone(user.UserRepository.authenticate("admin", "123456"))
        self.assertIsNotNone(user.UserRepository.authenticate("admin", "changed"))

    def test_rbac_feature_and_menu_chain(self):
        admin_role = RoleRepository.get_by_code("admin")
        user_role = RoleRepository.get_by_code("user")
        self.assertIsNotNone(admin_role)
        self.assertTrue(RoleRepository.has_feature(admin_role["id"], "user_management"))
        self.assertTrue(RoleRepository.has_feature(user_role["id"], "user_portal"))

        self.assertTrue(RoleRepository.create("auditor", "审计员", "只读审计角色", "admin"))
        auditor = RoleRepository.get_by_code("auditor")
        self.assertTrue(
            FeatureRepository.create(
                "audit_center", "审计中心", "/admin/modules/audit", "layui-icon-log",
                "核心工作区", "查看审计记录", 35,
            )
        )
        feature = next(item for item in FeatureRepository.list_features() if item["code"] == "audit_center")
        RoleRepository.set_features(auditor["id"], [feature["id"]])
        self.assertTrue(RoleRepository.has_feature(auditor["id"], "audit_center"))
        self.assertTrue(MenuRepository.create(feature["id"], "审计中心", "layui-icon-log", "核心工作区", 35))
        self.assertEqual(MenuRepository.list_for_role(auditor["id"])[0]["code"], "audit_center")

        FeatureRepository.set_enabled(feature["id"], False)
        self.assertFalse(RoleRepository.has_feature(auditor["id"], "audit_center"))
        self.assertEqual(MenuRepository.list_for_role(auditor["id"]), [])
        FeatureRepository.set_enabled(feature["id"], True)
        menu = next(item for item in MenuRepository.list_menus() if item["feature_code"] == "audit_center")
        MenuRepository.set_enabled(menu["id"], False)
        self.assertEqual(MenuRepository.list_for_role(auditor["id"]), [])

    def test_user_management_crud_and_disabled_login(self):
        admin_role = RoleRepository.get_by_code("admin")
        self.assertTrue(user.UserRepository.create_user("operator", "123456", role_id=admin_role["id"]))
        record = user.UserRepository.get_user_by_username("operator")
        self.assertEqual(record["role_scope"], "admin")
        self.assertTrue(user.UserRepository.update_user(record["id"], "operator2", admin_role["id"], "disabled"))
        self.assertIsNone(user.UserRepository.authenticate("operator2", "123456"))
        self.assertTrue(user.UserRepository.delete_user(record["id"]))
        self.assertIsNone(user.UserRepository.get_user_by_username("operator2"))

    def test_legacy_users_table_is_migrated(self):
        self.db_path.unlink()
        salt = b"0123456789abcdef"
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "INSERT INTO users (username, password_hash, salt, role) VALUES (?, ?, ?, ?)",
                ("legacy_admin", user._hash_password("123456", salt), salt.hex(), "admin"),
            )
            connection.commit()
        db.init_db()
        migrated = user.UserRepository.authenticate("legacy_admin", "123456")
        self.assertIsNotNone(migrated)
        self.assertEqual(migrated["role_scope"], "admin")
        self.assertTrue(RoleRepository.has_feature(migrated["role_id"], "user_management"))


if __name__ == "__main__":
    unittest.main()
