"""day6-2 数据迁移、瞭源、采集、仓库与模型 Repository 测试。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app.models import db, user
from app.models.lookout import CollectionRepository
from app.models.model_engine import ModelRepository
from app.models.rbac import RoleRepository
from app.models.source import RuleRepository, SourceRepository
from app.models.user import UserRepository
from app.models.warehouse import WarehouseRepository


class V02RepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "v02-test.db"
        self.db_patch = patch.object(db, "DATABASE_PATH", self.db_path)
        self.db_patch.start()
        db.init_db()
        UserRepository.ensure_admin("admin", "123456")

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_superadmin_is_repository_protected(self):
        """即使绕过页面，默认超管也不能走普通用户更新/删除接口。"""
        admin = UserRepository.get_user_by_username("admin")
        user_role = RoleRepository.get_by_code("user")
        self.assertTrue(admin["is_superadmin"])

        self.assertFalse(
            UserRepository.update_user(
                admin["id"], "renamed_admin", user_role["id"], "disabled", "654321"
            )
        )
        self.assertFalse(UserRepository.delete_user(admin["id"]))

        unchanged = UserRepository.get_user_by_username("admin")
        self.assertIsNotNone(unchanged)
        self.assertTrue(unchanged["is_superadmin"])
        self.assertEqual(unchanged["status"], "enabled")
        self.assertIsNotNone(UserRepository.authenticate("admin", "123456"))

    def test_v01_database_migrates_and_backfills_admin_permissions(self):
        """覆盖旧库已有部分授权时，新功能漏授权和旧菜单不改名的回归。"""
        self.db_path.unlink(missing_ok=True)
        salt = b"0123456789abcdef"
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.executescript(
                """
                CREATE TABLE roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    access_scope TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    is_system INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    role_id INTEGER REFERENCES roles(id),
                    status TEXT NOT NULL DEFAULT 'enabled',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE features (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    route TEXT NOT NULL UNIQUE,
                    icon TEXT NOT NULL DEFAULT 'layui-icon-app',
                    category TEXT NOT NULL DEFAULT '自定义功能',
                    description TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 100,
                    is_system INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE role_features (
                    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                    feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (role_id, feature_id)
                );
                CREATE TABLE menus (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feature_id INTEGER NOT NULL UNIQUE REFERENCES features(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    icon TEXT NOT NULL DEFAULT 'layui-icon-app',
                    category TEXT NOT NULL DEFAULT '自定义功能',
                    sort_order INTEGER NOT NULL DEFAULT 100,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    is_system INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO roles (code, name, access_scope, is_system)
                    VALUES ('user', '普通用户', 'user', 1);
                INSERT INTO roles (code, name, access_scope, is_system)
                    VALUES ('admin', '系统管理员', 'admin', 1);
                INSERT INTO features
                    (code, name, route, icon, category, description, sort_order, is_system)
                    VALUES ('dashboard', '工作台', '/admin/', 'layui-icon-console',
                            '核心工作区', '旧工作台', 10, 1);
                INSERT INTO features
                    (code, name, route, icon, category, description, sort_order, is_system)
                    VALUES ('lookout_management', '瞭望管理', '/admin/modules/lookout',
                            'layui-icon-chart-screen', '数据与智能', '旧入口', 60, 1);
                INSERT INTO features
                    (code, name, route, icon, category, description, sort_order, is_system)
                    VALUES ('data_management', '数据管理', '/admin/modules/data',
                            'layui-icon-diamond', '数据与智能', '旧入口', 70, 1);
                INSERT INTO features
                    (code, name, route, icon, category, description, sort_order, is_system)
                    VALUES ('collection_management', '采集管理', '/admin/modules/collect',
                            'layui-icon-download-circle', '数据与智能', '旧入口', 80, 1);
                INSERT INTO features
                    (code, name, route, icon, category, description, sort_order, is_system)
                    VALUES ('model_engine', '模型引擎', '/admin/modules/models',
                            'layui-icon-engine', '数据与智能', '旧入口', 100, 1);
                INSERT INTO role_features (role_id, feature_id)
                    SELECT r.id, f.id FROM roles r, features f
                    WHERE r.code = 'admin' AND f.code = 'dashboard';
                INSERT INTO menus (feature_id, title, icon, category, sort_order, is_system)
                    SELECT id, '瞭望管理', icon, category, sort_order, 1
                    FROM features WHERE code = 'lookout_management';
                """
            )
            admin_role_id = connection.execute(
                "SELECT id FROM roles WHERE code = 'admin'"
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO users
                    (username, password_hash, salt, role, role_id, status)
                VALUES (?, ?, ?, 'admin', ?, 'enabled')
                """,
                ("admin", user._hash_password("123456", salt), salt.hex(), admin_role_id),
            )
            connection.commit()

        db.init_db()
        migrated_admin = UserRepository.authenticate("admin", "123456")
        self.assertIsNotNone(migrated_admin)
        self.assertTrue(migrated_admin["is_superadmin"])

        expected = {
            "lookout_management": ("瞭望采集", "/admin/lookout"),
            "data_management": ("数据仓库", "/admin/warehouse"),
            "collection_management": ("瞭源管理", "/admin/sources"),
            "model_engine": ("模型引擎", "/admin/models"),
        }
        with db.connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT f.code, f.name, f.route
                FROM role_features rf
                JOIN roles r ON r.id = rf.role_id
                JOIN features f ON f.id = rf.feature_id
                WHERE r.code = 'admin' AND f.code IN (?, ?, ?, ?)
                """,
                tuple(expected),
            ).fetchall()
            self.assertEqual({row["code"] for row in rows}, set(expected))
            for row in rows:
                self.assertEqual((row["name"], row["route"]), expected[row["code"]])
            menu_title = connection.execute(
                """
                SELECT m.title FROM menus m JOIN features f ON f.id = m.feature_id
                WHERE f.code = 'lookout_management'
                """
            ).fetchone()["title"]
            self.assertEqual(menu_title, "瞭望采集")
            self.assertIsNotNone(
                connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = 2"
                ).fetchone()
            )

        # 初始化必须可重复执行，且唯一数据数量保持稳定。
        db.init_db()
        with db.connection_scope() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM schema_migrations WHERE version = 2"
                ).fetchone()["count"],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM users WHERE is_superadmin = 1"
                ).fetchone()["count"],
                1,
            )

    def test_source_rules_validate_headers_urls_and_enabled_state(self):
        source_id = SourceRepository.create(
            code="public_news",
            name="公开新闻测试源",
            base_url="https://example.com/search",
            headers_json={"User-Agent": "DataFinderAgentOS-Test", "Accept": "text/html"},
        )
        self.assertIsInstance(source_id, int)
        source = SourceRepository.get(source_id)
        self.assertEqual(source["default_headers"]["User-Agent"], "DataFinderAgentOS-Test")

        with self.assertRaises(ValueError):
            SourceRepository.create(
                code="bad_cookie",
                name="危险请求头",
                base_url="https://example.com",
                headers_json={"Cookie": "private=value"},
            )
        with self.assertRaises(ValueError):
            SourceRepository.create(
                code="bad_scheme",
                name="非法协议",
                base_url="file:///etc/passwd",
            )

        rule_id = RuleRepository.create(
            source_id=source_id,
            name="关键词分页规则",
            keyword_param="keyword",
            page_param="offset",
            page_start=0,
            page_step=10,
            page_size=12,
            fixed_params={"type": "news"},
            request_headers={"Accept-Language": "zh-CN"},
            parser_type="generic_links",
        )
        self.assertIsInstance(rule_id, int)
        rule = RuleRepository.get(rule_id)
        self.assertEqual(rule["fixed_params"], {"type": "news"})
        self.assertEqual(rule["page_step"], 10)

        enabled_rules, _ = RuleRepository.list(enabled_only=True, page_size=200)
        self.assertIn(rule_id, {item["id"] for item in enabled_rules})
        self.assertTrue(SourceRepository.toggle(source_id))
        enabled_rules, _ = RuleRepository.list(enabled_only=True, page_size=200)
        self.assertNotIn(rule_id, {item["id"] for item in enabled_rules})

    def test_collection_and_warehouse_import_are_idempotent(self):
        rules, _ = RuleRepository.list(enabled_only=True, page=1, page_size=200)
        rule = next(item for item in rules if item["parser_type"] == "baidu_news")
        admin = UserRepository.get_user_by_username("admin")
        run_id = CollectionRepository.create_run(
            rule_id=rule["id"],
            user_id=admin["id"],
            keyword="四川",
            page=1,
            page_size=12,
        )
        saved = CollectionRepository.save_results(
            run_id,
            [
                {
                    "title": "四川公开新闻一",
                    "url": "https://news.example.com/item/1",
                    "summary": "摘要一",
                    "source_name": "测试来源",
                    "published_at": "2026-07-13",
                },
                {
                    "title": "同一 URL 重复结果",
                    "url": "https://news.example.com/item/1",
                },
                {
                    "title": "四川公开新闻二",
                    "url": "https://news.example.com/item/2",
                    "raw_data": {"kind": "fixture"},
                },
                {"title": "非法协议", "url": "javascript:alert(1)"},
            ],
        )
        self.assertEqual(len(saved), 2)
        self.assertEqual(CollectionRepository.get_run(run_id)["status"], "success")

        result_ids = [item["id"] for item in saved]
        inserted, skipped = WarehouseRepository.import_results(result_ids, admin["id"])
        self.assertEqual((inserted, skipped), (2, 0))
        inserted_again, skipped_again = WarehouseRepository.import_results(
            result_ids, admin["id"]
        )
        self.assertEqual((inserted_again, skipped_again), (0, 2))

        items, total = WarehouseRepository.list(keyword="四川", page=1, page_size=10)
        self.assertEqual(total, 2)
        self.assertEqual(len(items), 2)
        self.assertTrue(WarehouseRepository.set_deep_collected(items[0]["id"], True))
        self.assertTrue(WarehouseRepository.get(items[0]["id"])["deep_collected"])

        deep_items, deep_total = WarehouseRepository.list(deep_status="1")
        self.assertEqual(deep_total, 1)
        self.assertEqual(deep_items[0]["id"], items[0]["id"])

    def test_model_filter_default_and_usage_statistics(self):
        admin = UserRepository.get_user_by_username("admin")
        text_id = ModelRepository.create(
            name="文本问数模型",
            model_name="demo-text",
            provider="OpenAI Compatible",
            model_type="text",
            base_url="https://models.example.com/v1",
            api_key_env="OPENAI_API_KEY",
            temperature=0.4,
            top_p=0.9,
            max_tokens=2048,
            context_messages=8,
            created_by=admin["id"],
        )
        image_id = ModelRepository.create(
            name="图像生成模型",
            model_name="demo-image",
            provider="OpenAI Compatible",
            model_type="image",
            base_url="https://models.example.com/v1",
            api_key_env="OPENAI_API_KEY",
            is_default=True,
            created_by=admin["id"],
        )
        self.assertIsInstance(text_id, int)
        self.assertIsInstance(image_id, int)
        self.assertEqual(ModelRepository.get_default()["id"], image_id)

        image_models, image_total = ModelRepository.list(model_type="image")
        self.assertEqual(image_total, 1)
        self.assertEqual(image_models[0]["id"], image_id)
        text_models, text_total = ModelRepository.list(model_type="text")
        self.assertEqual(text_total, 1)
        self.assertEqual(text_models[0]["id"], text_id)

        with self.assertRaises(ValueError):
            ModelRepository.create(
                name="非法分类模型",
                model_name="bad-type",
                model_type="unknown",
                base_url="https://models.example.com/v1",
            )
        with self.assertRaises(ValueError):
            ModelRepository.create(
                name="地址携带凭据",
                model_name="bad-url",
                model_type="text",
                base_url="https://user:password@models.example.com/v1",
            )

        usage_id = ModelRepository.record_usage(
            model_id=image_id,
            user_id=admin["id"],
            prompt_tokens=12,
            completion_tokens=8,
            total_tokens=20,
            latency_ms=345,
            success=True,
        )
        self.assertIsInstance(usage_id, int)
        summary = ModelRepository.usage_summary(image_id)
        self.assertEqual(summary["usage_count"], 1)
        self.assertEqual(summary["prompt_tokens"], 12)
        self.assertEqual(summary["completion_tokens"], 8)
        self.assertEqual(summary["total_tokens"], 20)
        self.assertEqual(int(summary["avg_latency_ms"]), 345)

        # 停用当前默认模型后必须自动切换到仍启用的模型。
        self.assertTrue(ModelRepository.toggle(image_id))
        self.assertFalse(ModelRepository.get(image_id)["enabled"])
        self.assertFalse(ModelRepository.set_default(image_id))
        self.assertEqual(ModelRepository.get_default()["id"], text_id)


if __name__ == "__main__":
    unittest.main()
