"""Test collection sources and rules."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import db
from app.models.db import connection_scope
from app.models.source import RuleRepository, SourceRepository


class TestCollectionSources(unittest.TestCase):
    """Test collection source management."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DATABASE_PATH", Path(self.temp_dir.name) / "sources.db")
        self.db_patch.start()
        db.init_db()
        with connection_scope() as connection:
            connection.execute("DELETE FROM collection_rules")
            connection.execute("DELETE FROM lookout_sources")
            connection.commit()
        self.sources = [
            {
                "code": "baidu_news",
                "name": "百度新闻",
                "base_url": "https://www.baidu.com/s",
                "description": "百度新闻搜索源",
            },
            {
                "code": "scu_news",
                "name": "四川大学新闻网",
                "base_url": "https://news.scu.edu.cn/",
                "description": "四川大学官方新闻",
            },
            {
                "code": "bing_news",
                "name": "Bing 新闻",
                "base_url": "https://www.bing.com/news/search",
                "description": "公开新闻搜索",
            },
        ]

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_source_creation(self):
        """Test creating collection sources."""
        for source in self.sources:
            source_id = SourceRepository.create(**source, enabled=True)
            self.assertIsNotNone(source_id)
            self.assertGreater(source_id, 0)

            # Verify source was created
            created = SourceRepository.get(source_id)
            self.assertIsNotNone(created)
            self.assertEqual(created["code"], source["code"])
            self.assertEqual(created["name"], source["name"])
            self.assertEqual(created["base_url"], source["base_url"])

    def test_source_list(self):
        """Test listing sources."""
        with connection_scope() as connection:
            connection.execute("DELETE FROM lookout_sources")
            connection.commit()

        for source in self.sources:
            SourceRepository.create(**source, enabled=True)

        sources, total = SourceRepository.list(page=1, page_size=10)
        self.assertEqual(total, 3)
        self.assertEqual(len(sources), 3)

    def test_source_update(self):
        """Test updating a source."""
        source_id = SourceRepository.create(**self.sources[0], enabled=True)
        self.assertIsNotNone(source_id)

        updated = SourceRepository.update(
            source_id, name="百度新闻(更新)", description="更新后的描述"
        )
        self.assertTrue(updated)

        source = SourceRepository.get(source_id)
        self.assertEqual(source["name"], "百度新闻(更新)")
        self.assertEqual(source["description"], "更新后的描述")

    def test_source_toggle(self):
        """Test toggling source enabled status."""
        source_id = SourceRepository.create(**self.sources[0], enabled=True)
        source = SourceRepository.get(source_id)
        self.assertTrue(source["enabled"])

        toggled = SourceRepository.toggle(source_id)
        self.assertTrue(toggled)

        source = SourceRepository.get(source_id)
        self.assertFalse(source["enabled"])

    def test_rule_creation(self):
        """Test creating collection rules."""
        # Create a source first
        source_id = SourceRepository.create(**self.sources[0], enabled=True)
        self.assertIsNotNone(source_id)

        # Create a rule
        rule_id = RuleRepository.create(
            source_id=source_id,
            name="百度新闻采集规则",
            keyword_param="word",
            page_param="pn",
            page_start=0,
            page_step=10,
            page_size=12,
            parser_type="baidu_news",
            enabled=True,
        )
        self.assertIsNotNone(rule_id)
        self.assertGreater(rule_id, 0)

        # Verify rule
        rule = RuleRepository.get(rule_id)
        self.assertIsNotNone(rule)
        self.assertEqual(rule["name"], "百度新闻采集规则")
        self.assertEqual(rule["source_code"], self.sources[0]["code"])

    def test_rule_list_by_source(self):
        """Test listing rules by source."""
        source_id = SourceRepository.create(**self.sources[0], enabled=True)

        RuleRepository.create(
            source_id=source_id,
            name="规则1",
            keyword_param="word",
            parser_type="baidu_news",
            enabled=True,
        )

        rules, total = RuleRepository.list(source_id=source_id, page=1, page_size=10)
        self.assertEqual(total, 1)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["name"], "规则1")

    def test_real_sources_present(self):
        """Test that the configured public sources are present."""
        db.init_db()
        # This test verifies the database contains the configured sources.
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT code, name FROM lookout_sources
                WHERE code IN ('baidu_news', 'scu_news', 'bing_news', 'chinanews')
                """
            ).fetchall()

        self.assertEqual(len(rows), 4)


if __name__ == "__main__":
    unittest.main()
