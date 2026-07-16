"""采集任务管理服务 - 支持批量、单条和深度采集，包括进度追踪和失败重试。"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Optional

from app.models.db import connection_scope
from app.services.collector import CollectionError, CollectorService
from app.services.security_analysis import SecurityAnalyzer

LOGGER = logging.getLogger("collection_task")


class CollectionType(Enum):
    """采集类型枚举。"""
    BATCH = "batch"  # 批量采集
    SINGLE = "single"  # 单条采集
    DEEP = "deep"  # 深度采集


class TaskStatus(Enum):
    """任务状态枚举。"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PAUSED = "paused"


class CollectionTaskService:
    """采集任务管理服务。"""

    MAX_RETRIES = 3
    RETRY_DELAY = 1  # 秒

    @staticmethod
    def create_batch_task(
        rule_id: int,
        keyword: str,
        pages: int = 1,
        user_id: Optional[int] = None,
    ) -> Optional[int]:
        """创建批量采集任务。

        Args:
            rule_id: 采集规则ID
            keyword: 关键词
            pages: 采集页数
            user_id: 用户ID

        Returns:
            任务ID或None
        """
        try:
            with connection_scope() as connection:
                # 验证规则存在
                rule = connection.execute(
                    "SELECT id FROM collection_rules WHERE id = ?", (rule_id,)
                ).fetchone()
                if not rule:
                    return None

                # 创建任务记录
                cursor = connection.execute(
                    """
                    INSERT INTO collection_runs
                        (rule_id, user_id, keyword, page_number, status)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (rule_id, user_id, keyword, pages, "pending"),
                )
                connection.commit()
                return int(cursor.lastrowid)
        except Exception as exc:
            LOGGER.exception("Failed to create batch task", extra={"rule_id": rule_id})
            return None

    @staticmethod
    def create_single_task(
        rule_id: int,
        keyword: str,
        page: int = 1,
        user_id: Optional[int] = None,
    ) -> Optional[int]:
        """创建单条采集任务（单页采集）。

        Args:
            rule_id: 采集规则ID
            keyword: 关键词
            page: 页码
            user_id: 用户ID

        Returns:
            任务ID或None
        """
        return CollectionTaskService.create_batch_task(
            rule_id=rule_id,
            keyword=keyword,
            pages=1,
            user_id=user_id,
        )

    @staticmethod
    def create_deep_task(
        warehouse_item_id: int,
        employee_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> Optional[int]:
        """创建深度采集任务。

        Args:
            warehouse_item_id: 仓库项目ID
            employee_id: 数字员工ID
            user_id: 用户ID

        Returns:
            任务ID或None
        """
        try:
            with connection_scope() as connection:
                # 验证仓库项存在
                item = connection.execute(
                    "SELECT id FROM warehouse_items WHERE id = ?", (warehouse_item_id,)
                ).fetchone()
                if not item:
                    return None

                # 创建深度采集任务
                cursor = connection.execute(
                    """
                    INSERT INTO deep_collection_tasks
                        (warehouse_item_id, employee_id, started_by, status)
                    VALUES (?, ?, ?, ?)
                    """,
                    (warehouse_item_id, employee_id, user_id, "pending"),
                )
                connection.commit()
                return int(cursor.lastrowid)
        except Exception as exc:
            LOGGER.exception(
                "Failed to create deep task",
                extra={"warehouse_item_id": warehouse_item_id},
            )
            return None

    @staticmethod
    async def execute_batch_task(
        task_id: int,
        rule_dict: dict,
        keyword: str,
        pages: int = 1,
    ) -> tuple[int, int]:
        """执行批量采集任务，支持多页采集和重试。

        Args:
            task_id: 任务ID
            rule_dict: 采集规则字典
            keyword: 关键词
            pages: 采集页数

        Returns:
            (成功数, 失败数)元组
        """
        success_count = 0
        failed_count = 0

        # 更新任务状态为运行中
        with connection_scope() as connection:
            connection.execute(
                "UPDATE collection_runs SET status = ? WHERE id = ?",
                ("running", task_id),
            )
            connection.commit()

        try:
            for page in range(1, pages + 1):
                retry_count = 0
                while retry_count < CollectionTaskService.MAX_RETRIES:
                    try:
                        results = await CollectorService.collect(
                            rule=rule_dict,
                            keyword=keyword,
                            page=page,
                        )

                        # 保存采集结果
                        with connection_scope() as connection:
                            for result in results:
                                try:
                                    # 执行安全分析
                                    risk_level, analysis = SecurityAnalyzer.analyze(
                                        title=result.get("title", ""),
                                        summary=result.get("summary", ""),
                                    )

                                    cursor = connection.execute(
                                        """
                                        INSERT INTO collection_results
                                            (run_id, rule_id, title, url, summary,
                                             source_name, published_at, raw_data)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                        """,
                                        (
                                            task_id,
                                            rule_dict.get("id"),
                                            result.get("title", "")[:300],
                                            result.get("url", "")[:2000],
                                            result.get("summary", "")[:2000],
                                            result.get("source_name", "")[:100],
                                            result.get("published_at", "")[:100],
                                            json.dumps(
                                                result.get("raw_data", {}),
                                                ensure_ascii=False,
                                                default=str,
                                            ),
                                        ),
                                    )
                                    result_id = cursor.lastrowid

                                    # 也保存到仓库并关联安全分析
                                    connection.execute(
                                        """
                                        INSERT OR IGNORE INTO warehouse_items
                                            (source_result_id, rule_id, title, url, summary,
                                             source_name, published_at, raw_data, risk_level,
                                             security_analysis, keywords)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """,
                                        (
                                            result_id,
                                            rule_dict.get("id"),
                                            result.get("title", "")[:300],
                                            result.get("url", "")[:2000],
                                            result.get("summary", "")[:2000],
                                            result.get("source_name", "")[:100],
                                            result.get("published_at", "")[:100],
                                            json.dumps(
                                                result.get("raw_data", {}),
                                                ensure_ascii=False,
                                                default=str,
                                            ),
                                            risk_level,
                                            json.dumps(analysis, ensure_ascii=False, default=str),
                                            ",".join(analysis.get("matched_words", []))[:500],
                                        ),
                                    )

                                    success_count += 1
                                except Exception as exc:
                                    LOGGER.warning(
                                        "Failed to insert collection result",
                                        extra={"url": result.get("url"), "error": str(exc)},
                                    )
                                    failed_count += 1
                            connection.commit()
                        break

                    except CollectionError as exc:
                        retry_count += 1
                        LOGGER.warning(
                            "Collection attempt failed, will retry",
                            extra={
                                "task_id": task_id,
                                "page": page,
                                "retry": retry_count,
                                "error": str(exc),
                            },
                        )
                        if retry_count < CollectionTaskService.MAX_RETRIES:
                            await asyncio.sleep(CollectionTaskService.RETRY_DELAY)
                        else:
                            failed_count += 1
                    except Exception as exc:
                        LOGGER.exception(
                            "Unexpected error during collection",
                            extra={"task_id": task_id, "page": page},
                        )
                        failed_count += 1
                        break

            # 更新任务状态和计数
            with connection_scope() as connection:
                status = "success" if failed_count == 0 else "failed" if success_count == 0 else "partial"
                connection.execute(
                    """
                    UPDATE collection_runs
                    SET status = ?, result_count = ?,
                        finished_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (status if status in ("success", "failed") else "success", success_count, task_id),
                )
                connection.commit()

        except Exception as exc:
            LOGGER.exception("Batch task execution failed", extra={"task_id": task_id})
            with connection_scope() as connection:
                connection.execute(
                    """
                    UPDATE collection_runs
                    SET status = ?, error_message = ?,
                        finished_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    ("failed", str(exc)[:500], task_id),
                )
                connection.commit()
            failed_count += 1

        return success_count, failed_count

    @staticmethod
    def get_task_progress(task_id: int) -> Optional[dict]:
        """获取任务进度。

        Args:
            task_id: 任务ID

        Returns:
            任务进度字典或None
        """
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT id, status, result_count, error_message,
                       created_at, finished_at
                FROM collection_runs
                WHERE id = ?
                """,
                (task_id,),
            ).fetchone()

            if not row:
                return None

            return {
                "id": int(row["id"]),
                "status": str(row["status"]),
                "result_count": int(row["result_count"]),
                "error_message": str(row["error_message"]),
                "created_at": str(row["created_at"]),
                "finished_at": str(row["finished_at"] or ""),
            }

    @staticmethod
    def retry_failed_task(task_id: int) -> bool:
        """重新尝试失败的任务。

        Args:
            task_id: 任务ID

        Returns:
            是否成功重置任务状态
        """
        try:
            with connection_scope() as connection:
                task = connection.execute(
                    "SELECT id FROM collection_runs WHERE id = ? AND status = ?",
                    (task_id, "failed"),
                ).fetchone()

                if not task:
                    return False

                connection.execute(
                    """
                    UPDATE collection_runs
                    SET status = ?, result_count = 0, error_message = '',
                        finished_at = NULL
                    WHERE id = ?
                    """,
                    ("pending", task_id),
                )
                connection.commit()
                return True
        except Exception as exc:
            LOGGER.exception("Failed to retry task", extra={"task_id": task_id})
            return False

    @staticmethod
    def cancel_task(task_id: int) -> bool:
        """取消任务。

        Args:
            task_id: 任务ID

        Returns:
            是否成功取消
        """
        try:
            with connection_scope() as connection:
                task = connection.execute(
                    "SELECT status FROM collection_runs WHERE id = ?", (task_id,)
                ).fetchone()

                if not task or task["status"] in ("success", "failed"):
                    return False

                connection.execute(
                    """
                    UPDATE collection_runs
                    SET status = ?, finished_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    ("paused", task_id),
                )
                connection.commit()
                return True
        except Exception as exc:
            LOGGER.exception("Failed to cancel task", extra={"task_id": task_id})
            return False

    @staticmethod
    def batch_delete_items(item_ids: list[int]) -> int:
        """批量删除仓库项。

        Args:
            item_ids: 仓库项ID列表

        Returns:
            删除的项数
        """
        if not item_ids:
            return 0

        try:
            # 限制最多删除1000条
            ids_to_delete = item_ids[:1000]
            with connection_scope() as connection:
                placeholders = ",".join("?" * len(ids_to_delete))
                cursor = connection.execute(
                    f"DELETE FROM warehouse_items WHERE id IN ({placeholders})",
                    ids_to_delete,
                )
                connection.commit()
                return cursor.rowcount
        except Exception as exc:
            LOGGER.exception("Failed to batch delete items")
            return 0

    @staticmethod
    def batch_mark_deep_collection(item_ids: list[int], employee_id: Optional[int] = None) -> int:
        """批量标记仓库项为待深度采集。

        Args:
            item_ids: 仓库项ID列表
            employee_id: 数字员工ID

        Returns:
            创建的任务数
        """
        if not item_ids:
            return 0

        created_count = 0
        ids_to_process = item_ids[:500]  # 限制最多处理500条

        try:
            for item_id in ids_to_process:
                task_id = CollectionTaskService.create_deep_task(
                    warehouse_item_id=item_id,
                    employee_id=employee_id,
                )
                if task_id:
                    created_count += 1
        except Exception as exc:
            LOGGER.exception("Failed to batch mark deep collection")

        return created_count
