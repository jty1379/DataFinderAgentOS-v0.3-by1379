"""Collection task lifecycle regression tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.models import db
from app.models.db import connection_scope
from app.models.source import RuleRepository, SourceRepository
from app.services.collection_task import CollectionTaskService
from app.services.collector import CollectionError


class TestCollectionTaskLifecycle(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            db, "DATABASE_PATH", Path(self.temp_dir.name) / "collection-task.db"
        )
        self.db_patch.start()
        db.init_db()
        source_id = SourceRepository.create(
            code="task_test",
            name="任务测试源",
            base_url="https://example.com/search",
            enabled=True,
        )
        self.rule_id = RuleRepository.create(
            source_id=source_id,
            name="生命周期规则",
            keyword_param="word",
            page_param="page",
            page_start=1,
            page_step=1,
            page_size=12,
            parser_type="generic_links",
            enabled=True,
        )

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    async def test_batch_task_success_and_real_progress(self):
        task_id = CollectionTaskService.create_batch_task(self.rule_id, "成都", pages=2)
        collector = AsyncMock(
            side_effect=[
                [{"title": "第一页新闻", "url": "https://example.com/news/1"}],
                [{"title": "第二页新闻", "url": "https://example.com/news/2"}],
            ]
        )
        with patch("app.services.collection_task.CollectorService.collect", collector):
            result = await CollectionTaskService.execute_task(task_id)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["progress"], 100)
        self.assertEqual(result["processed_pages"], 2)
        self.assertEqual(result["result_count"], 2)
        self.assertTrue(any(log["step"] == "finished" for log in result["logs"]))

    async def test_partial_task_retry_is_idempotent(self):
        task_id = CollectionTaskService.create_batch_task(self.rule_id, "四川", pages=2)
        first_collector = AsyncMock(
            side_effect=[
                [{"title": "已保存新闻", "url": "https://example.com/news/saved"}],
                CollectionError("第二页暂不可用"),
                CollectionError("第二页暂不可用"),
                CollectionError("第二页暂不可用"),
            ]
        )
        with (
            patch("app.services.collection_task.CollectorService.collect", first_collector),
            patch.object(CollectionTaskService, "RETRY_DELAY", 0),
        ):
            result = await CollectionTaskService.execute_task(task_id)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["failed_count"], 1)
        self.assertTrue(CollectionTaskService.retry_failed_task(task_id))

        retry_collector = AsyncMock(
            side_effect=[
                [{"title": "已保存新闻", "url": "https://example.com/news/saved"}],
                [{"title": "补采新闻", "url": "https://example.com/news/retry"}],
            ]
        )
        with patch("app.services.collection_task.CollectorService.collect", retry_collector):
            retried = await CollectionTaskService.execute_task(task_id)

        self.assertEqual(retried["status"], "success")
        self.assertEqual(retried["result_count"], 2)
        self.assertEqual(retried["retry_count"], 1)

    async def test_cancel_and_restart_recovery(self):
        pending_id = CollectionTaskService.create_single_task(self.rule_id, "取消")
        self.assertTrue(CollectionTaskService.cancel_task(pending_id))
        self.assertEqual(
            CollectionTaskService.get_task_progress(pending_id)["status"], "cancelled"
        )

        interrupted_id = CollectionTaskService.create_single_task(self.rule_id, "恢复")
        with connection_scope() as connection:
            connection.execute(
                "UPDATE collection_runs SET status='running' WHERE id=?", (interrupted_id,)
            )
            connection.commit()
        recovered = CollectionTaskService.recover_interrupted()
        self.assertIn(interrupted_id, recovered)
        progress = CollectionTaskService.get_task_progress(interrupted_id)
        self.assertEqual(progress["status"], "pending")
        self.assertEqual(progress["retry_count"], 1)


if __name__ == "__main__":
    unittest.main()
