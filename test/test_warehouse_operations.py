"""Test warehouse operations and deduplication."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import db
from app.models.db import connection_scope
from app.models.warehouse import WarehouseRepository


class TestWarehouseOperations(unittest.TestCase):
    """Test warehouse data operations."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DATABASE_PATH", Path(self.temp_dir.name) / "warehouse.db")
        self.db_patch.start()
        db.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_warehouse_item_creation(self):
        """Test creating warehouse items."""
        items_data = [
            {
                "title": "测试标题1",
                "url": "https://example.com/1",
                "summary": "测试摘要1",
                "source_name": "百度新闻",
            },
            {
                "title": "测试标题2",
                "url": "https://example.com/2",
                "summary": "测试摘要2",
                "source_name": "四川大学新闻网",
            },
        ]

        for item in items_data:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO warehouse_items
                        (title, url, summary, source_name)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        item["title"],
                        item["url"],
                        item["summary"],
                        item["source_name"],
                    ),
                )
                connection.commit()
                self.assertGreater(cursor.lastrowid, 0)

    def test_warehouse_risk_level_update(self):
        """Test updating risk levels."""
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                INSERT INTO warehouse_items
                    (title, url, summary, source_name)
                VALUES (?, ?, ?, ?)
                """,
                ("测试", "https://example.com/test", "摘要", "来源"),
            )
            connection.commit()
            item_id = cursor.lastrowid

        # Update risk level
        result = WarehouseRepository.update_risk_level(
            item_id=item_id,
            risk_level="high",
            security_analysis={"matched_keywords": ["敏感词"], "risk_score": 8.5},
        )
        self.assertTrue(result)

        # Verify update
        item = WarehouseRepository.get(item_id)
        self.assertEqual(item["risk_level"], "high")
        self.assertIsInstance(item["security_analysis"], dict)

    def test_keywords_update(self):
        """Test updating keywords."""
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                INSERT INTO warehouse_items
                    (title, url, summary, source_name)
                VALUES (?, ?, ?, ?)
                """,
                ("关键词测试", "https://example.com/keywords", "摘要", "来源"),
            )
            connection.commit()
            item_id = cursor.lastrowid

        result = WarehouseRepository.update_keywords(
            item_id=item_id, keywords="关键词1,关键词2", matched_words="敏感词"
        )
        self.assertTrue(result)

        item = WarehouseRepository.get(item_id)
        self.assertEqual(item["keywords"], "关键词1,关键词2")
        self.assertEqual(item["matched_words"], "敏感词")

    def test_batch_delete(self):
        """Test batch deletion."""
        item_ids = []
        with connection_scope() as connection:
            for i in range(3):
                cursor = connection.execute(
                    """
                    INSERT INTO warehouse_items
                        (title, url, summary, source_name)
                    VALUES (?, ?, ?, ?)
                    """,
                    (f"标题{i}", f"https://example.com/{i}", "摘要", "来源"),
                )
                item_ids.append(cursor.lastrowid)
            connection.commit()

        # Batch delete
        deleted = WarehouseRepository.batch_delete(item_ids[:2])
        self.assertEqual(deleted, 2)

        # Verify remaining
        items, total = WarehouseRepository.list(page=1, page_size=10)
        self.assertEqual(total, 1)

    def test_deduplication(self):
        """Test deduplication by URL."""
        with connection_scope() as connection:
            # Insert duplicate URLs
            for i in range(2):
                connection.execute(
                    """
                    INSERT INTO warehouse_items
                        (title, url, summary, source_name)
                    VALUES (?, ?, ?, ?)
                    """,
                    (f"标题{i}", "https://example.com/duplicate", "摘要", "来源"),
                )
            connection.commit()

        items_before, total_before = WarehouseRepository.list(page=1, page_size=10)
        self.assertEqual(total_before, 2)

        # Run deduplication
        deleted = WarehouseRepository.deduplication()
        self.assertEqual(deleted, 1)

        items_after, total_after = WarehouseRepository.list(page=1, page_size=10)
        self.assertEqual(total_after, 1)

    def test_get_by_risk_level(self):
        """Test filtering by risk level."""
        with connection_scope() as connection:
            for level in ("low", "normal", "high", "critical"):
                for i in range(2):
                    connection.execute(
                        """
                        INSERT INTO warehouse_items
                            (title, url, summary, source_name, risk_level)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            f"标题-{level}-{i}",
                            f"https://example.com/{level}/{i}",
                            "摘要",
                            "来源",
                            level,
                        ),
                    )
            connection.commit()

        high_items = WarehouseRepository.get_by_risk_level("high")
        self.assertEqual(len(high_items), 2)

        critical_items = WarehouseRepository.get_by_risk_level("critical")
        self.assertEqual(len(critical_items), 2)

    def test_summary_stats(self):
        """Test summary statistics."""
        with connection_scope() as connection:
            # Insert test data
            for i in range(5):
                risk = "critical" if i == 0 else "high" if i == 1 else "normal"
                connection.execute(
                    """
                    INSERT INTO warehouse_items
                        (title, url, summary, source_name, risk_level, deep_collected)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"标题{i}",
                        f"https://example.com/{i}",
                        "摘要",
                        "来源",
                        risk,
                        i < 2,
                    ),
                )
            connection.commit()

        stats = WarehouseRepository.get_summary_stats()
        self.assertEqual(stats["total_count"], 5)
        self.assertEqual(stats["deep_count"], 2)
        self.assertEqual(stats["critical_count"], 1)
        self.assertEqual(stats["high_count"], 1)
        self.assertGreaterEqual(stats["normal_count"], 0)

    def test_duplicate_detection(self):
        """Test duplicate URL detection."""
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                INSERT INTO warehouse_items
                    (title, url, summary, source_name)
                VALUES (?, ?, ?, ?)
                """,
                ("标题", "https://example.com/test", "摘要", "来源"),
            )
            connection.commit()

        # Check for duplicates
        duplicates = WarehouseRepository.get_duplicates(
            title="标题", url="https://example.com/test"
        )
        self.assertGreaterEqual(len(duplicates), 1)


if __name__ == "__main__":
    unittest.main()
