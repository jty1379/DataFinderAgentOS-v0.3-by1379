"""可恢复的采集任务生命周期服务。"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum

import tornado.ioloop

from app.models.db import connection_scope
from app.models.lookout import CollectionRepository
from app.models.source import RuleRepository
from app.services.collector import CollectionError, CollectorService

LOGGER = logging.getLogger("collection_task")


class CollectionType(Enum):
    SINGLE = "single"
    BATCH = "batch"
    DEEP = "deep"


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {
    TaskStatus.SUCCESS.value,
    TaskStatus.PARTIAL.value,
    TaskStatus.FAILED.value,
    TaskStatus.CANCELLED.value,
}


class CollectionTaskService:
    """创建、执行、取消、重试、恢复并查询普通采集任务。"""

    MAX_RETRIES = 3
    RETRY_DELAY = 1

    @staticmethod
    def _log(
        task_id: int,
        level: str,
        step: str,
        message: str,
        page_number: int | None = None,
    ) -> None:
        level = level if level in {"info", "success", "warning", "error"} else "info"
        with connection_scope() as connection:
            connection.execute(
                """INSERT INTO collection_run_logs
                   (run_id,level,step,message,page_number)
                   VALUES (?,?,?,?,?)""",
                (task_id, level, step[:80], message.strip()[:1000], page_number),
            )
            connection.commit()

    @staticmethod
    def _rule_available(rule_id: int) -> dict | None:
        rule = RuleRepository.get(rule_id)
        if not rule or not rule.get("enabled") or not rule.get("source_enabled"):
            return None
        return rule

    @classmethod
    def create_batch_task(
        cls,
        rule_id: int,
        keyword: str,
        pages: int = 1,
        user_id: int | None = None,
        *,
        start_page: int = 1,
        page_size: int | None = None,
    ) -> int | None:
        keyword = str(keyword or "").strip()
        if not 1 <= len(keyword) <= 100:
            raise ValueError("采集关键词需为 1—100 个字符")
        rule = cls._rule_available(int(rule_id))
        if not rule:
            return None
        pages = min(100, max(1, int(pages or 1)))
        start_page = min(1000, max(1, int(start_page or 1)))
        page_size = min(100, max(1, int(page_size or rule.get("page_size") or 12)))
        task_type = CollectionType.BATCH.value if pages > 1 else CollectionType.SINGLE.value
        with connection_scope() as connection:
            cursor = connection.execute(
                """INSERT INTO collection_runs
                   (rule_id,user_id,task_type,keyword,page_number,page_size,total_pages,status)
                   VALUES (?,?,?,?,?,?,?,'pending')""",
                (rule_id, user_id, task_type, keyword, start_page, page_size, pages),
            )
            connection.commit()
            task_id = int(cursor.lastrowid)
        cls._log(task_id, "info", "created", f"已创建{pages}页采集任务，从第{start_page}页开始")
        return task_id

    @classmethod
    def create_single_task(
        cls,
        rule_id: int,
        keyword: str,
        page: int = 1,
        user_id: int | None = None,
        *,
        page_size: int | None = None,
    ) -> int | None:
        return cls.create_batch_task(
            rule_id,
            keyword,
            pages=1,
            user_id=user_id,
            start_page=page,
            page_size=page_size,
        )

    @staticmethod
    def create_deep_task(
        warehouse_item_id: int,
        employee_id: int | None = None,
        user_id: int | None = None,
    ) -> int | None:
        try:
            with connection_scope() as connection:
                item = connection.execute(
                    "SELECT id FROM warehouse_items WHERE id=?", (warehouse_item_id,)
                ).fetchone()
                if not item:
                    return None
                cursor = connection.execute(
                    """INSERT INTO deep_collection_tasks
                       (warehouse_item_id,employee_id,started_by,status)
                       VALUES (?,?,?,'pending')""",
                    (warehouse_item_id, employee_id, user_id),
                )
                connection.commit()
                return int(cursor.lastrowid)
        except Exception:
            LOGGER.exception(
                "failed to create deep task",
                extra={"warehouse_item_id": warehouse_item_id, "event": "deep_task_create_failed"},
            )
            return None

    @classmethod
    def schedule(cls, task_id: int) -> None:
        """在当前 Tornado IOLoop 后台执行任务，HTTP 请求可立即返回。"""
        tornado.ioloop.IOLoop.current().spawn_callback(cls.execute_task, int(task_id))

    @staticmethod
    def _is_cancelled(task_id: int) -> bool:
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT status FROM collection_runs WHERE id=?", (task_id,)
            ).fetchone()
        return bool(row and row["status"] == TaskStatus.CANCELLED.value)

    @classmethod
    async def execute_task(cls, task_id: int) -> dict | None:
        """从数据库读取完整配置并执行任务，可用于新建、重试和启动恢复。"""
        with connection_scope() as connection:
            task = connection.execute(
                "SELECT * FROM collection_runs WHERE id=?", (int(task_id),)
            ).fetchone()
            if not task or task["status"] != TaskStatus.PENDING.value:
                return cls.get_task_progress(task_id)
            cursor = connection.execute(
                """UPDATE collection_runs
                   SET status='running',started_at=COALESCE(started_at,CURRENT_TIMESTAMP),
                       finished_at=NULL,cancelled_at=NULL,error_message='',updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND status='pending'""",
                (task_id,),
            )
            connection.commit()
            if cursor.rowcount != 1:
                return cls.get_task_progress(task_id)
            task = dict(task)

        rule = cls._rule_available(int(task["rule_id"] or 0))
        if not rule:
            cls._finish_failed(task_id, "采集规则不存在、所属瞭源已停用或规则已停用")
            return cls.get_task_progress(task_id)

        total_pages = max(1, int(task.get("total_pages") or 1))
        start_page = max(1, int(task.get("page_number") or 1))
        page_size = min(100, max(1, int(task.get("page_size") or 12)))
        processed_pages = 0
        failed_pages = 0
        errors: list[str] = []
        cls._log(task_id, "info", "started", f"开始执行，共{total_pages}页")

        try:
            for offset in range(total_pages):
                page = start_page + offset
                if cls._is_cancelled(task_id):
                    cls._log(task_id, "warning", "cancelled", "任务已由管理员取消", page)
                    break

                page_error = ""
                collected: list[dict] | None = None
                for attempt in range(1, cls.MAX_RETRIES + 1):
                    try:
                        cls._log(
                            task_id,
                            "info",
                            "request",
                            f"请求第{page}页，第{attempt}次尝试",
                            page,
                        )
                        collected = await CollectorService.collect(
                            rule,
                            str(task["keyword"]),
                            page=page,
                            page_size=page_size,
                        )
                        page_error = ""
                        break
                    except CollectionError as exc:
                        page_error = str(exc)[:500]
                        cls._log(
                            task_id,
                            "warning" if attempt < cls.MAX_RETRIES else "error",
                            "request",
                            f"第{page}页采集失败：{page_error}",
                            page,
                        )
                        if attempt < cls.MAX_RETRIES:
                            await asyncio.sleep(cls.RETRY_DELAY)
                    except Exception as exc:
                        page_error = "采集执行发生未预期错误"
                        LOGGER.exception(
                            "collection task page failed",
                            extra={"task_id": task_id, "event": "collection_task_page_failed"},
                        )
                        cls._log(task_id, "error", "request", f"第{page}页：{page_error}", page)
                        errors.append(str(exc)[:200])
                        break

                if cls._is_cancelled(task_id):
                    cls._log(task_id, "warning", "cancelled", "收到取消信号，停止写入结果", page)
                    break

                processed_pages += 1
                if collected is None:
                    failed_pages += 1
                    errors.append(page_error or f"第{page}页采集失败")
                else:
                    rows = CollectionRepository.append_results(task_id, collected)
                    message = (
                        f"第{page}页已完成，任务累计保存{len(rows)}条结果"
                        if collected
                        else f"第{page}页请求成功，但未解析到可用结果"
                    )
                    cls._log(
                        task_id,
                        "success" if collected else "warning",
                        "saved",
                        message,
                        page,
                    )

                cls._update_progress(
                    task_id,
                    processed_pages=processed_pages,
                    failed_pages=failed_pages,
                    total_pages=total_pages,
                    error_message=errors[-1] if errors else "",
                )

            if cls._is_cancelled(task_id):
                return cls.get_task_progress(task_id)
            cls._finish(task_id, failed_pages, errors)
        except Exception as exc:
            LOGGER.exception(
                "collection task execution failed",
                extra={"task_id": task_id, "event": "collection_task_failed"},
            )
            cls._finish_failed(task_id, str(exc)[:500] or "采集任务执行失败")
        return cls.get_task_progress(task_id)

    @classmethod
    async def execute_batch_task(
        cls,
        task_id: int,
        rule_dict: dict | None = None,
        keyword: str = "",
        pages: int = 1,
    ) -> tuple[int, int]:
        """兼容成员分支原有调用；执行参数以数据库任务记录为准。"""
        result = await cls.execute_task(task_id)
        if not result:
            return 0, 1
        return int(result["success_count"]), int(result["failed_count"])

    @staticmethod
    def _result_count(task_id: int, connection=None) -> int:
        if connection is not None:
            return int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM collection_results WHERE run_id=?",
                    (task_id,),
                ).fetchone()["count"]
            )
        with connection_scope() as scoped_connection:
            return CollectionTaskService._result_count(task_id, scoped_connection)

    @classmethod
    def _update_progress(
        cls,
        task_id: int,
        *,
        processed_pages: int,
        failed_pages: int,
        total_pages: int,
        error_message: str,
    ) -> None:
        with connection_scope() as connection:
            result_count = cls._result_count(task_id, connection)
            progress = min(99, round(processed_pages / max(total_pages, 1) * 100))
            connection.execute(
                """UPDATE collection_runs
                   SET processed_pages=?,result_count=?,success_count=?,failed_count=?,
                       progress=?,error_message=?,updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND status='running'""",
                (
                    processed_pages,
                    result_count,
                    result_count,
                    failed_pages,
                    progress,
                    error_message[:500],
                    task_id,
                ),
            )
            connection.commit()

    @classmethod
    def _finish(cls, task_id: int, failed_pages: int, errors: list[str]) -> None:
        with connection_scope() as connection:
            result_count = cls._result_count(task_id, connection)
            if failed_pages == 0:
                status = TaskStatus.SUCCESS.value
            elif result_count:
                status = TaskStatus.PARTIAL.value
            else:
                status = TaskStatus.FAILED.value
            connection.execute(
                """UPDATE collection_runs
                   SET status=?,result_count=?,success_count=?,failed_count=?,progress=100,
                       error_message=?,finished_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND status='running'""",
                (status, result_count, result_count, failed_pages, (errors[-1] if errors else "")[:500], task_id),
            )
            connection.commit()
        cls._log(
            task_id,
            "success" if status == TaskStatus.SUCCESS.value else "warning" if status == TaskStatus.PARTIAL.value else "error",
            "finished",
            f"任务结束：状态{status}，保存{result_count}条，失败页{failed_pages}个",
        )

    @classmethod
    def _finish_failed(cls, task_id: int, message: str) -> None:
        with connection_scope() as connection:
            result_count = cls._result_count(task_id, connection)
            status = TaskStatus.PARTIAL.value if result_count else TaskStatus.FAILED.value
            connection.execute(
                """UPDATE collection_runs
                   SET status=?,result_count=?,success_count=?,failed_count=failed_count+1,
                       progress=100,error_message=?,finished_at=CURRENT_TIMESTAMP,
                       updated_at=CURRENT_TIMESTAMP WHERE id=? AND status!='cancelled'""",
                (status, result_count, result_count, message.strip()[:500], task_id),
            )
            connection.commit()
        cls._log(task_id, "error", "finished", message)

    @staticmethod
    def list_tasks(
        *,
        keyword: str = "",
        status: str = "",
        task_type: str = "",
        rule_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        page = max(1, int(page or 1))
        page_size = min(100, max(1, int(page_size or 20)))
        clauses = ["(?='' OR cr.keyword LIKE ? OR r.name LIKE ? OR s.name LIKE ?)"]
        pattern = f"%{keyword.strip()}%"
        params: list[object] = [keyword.strip(), pattern, pattern, pattern]
        if status in {item.value for item in TaskStatus}:
            clauses.append("cr.status=?")
            params.append(status)
        if task_type in {CollectionType.SINGLE.value, CollectionType.BATCH.value}:
            clauses.append("cr.task_type=?")
            params.append(task_type)
        if rule_id:
            clauses.append("cr.rule_id=?")
            params.append(int(rule_id))
        where = " AND ".join(clauses)
        offset = (page - 1) * page_size
        with connection_scope() as connection:
            total = int(
                connection.execute(
                    """SELECT COUNT(*) AS count FROM collection_runs cr
                       LEFT JOIN collection_rules r ON r.id=cr.rule_id
                       LEFT JOIN lookout_sources s ON s.id=r.source_id
                       WHERE """ + where,
                    params,
                ).fetchone()["count"]
            )
            rows = connection.execute(
                """SELECT cr.*,r.name AS rule_name,s.name AS source_name,u.username AS operator_name
                   FROM collection_runs cr
                   LEFT JOIN collection_rules r ON r.id=cr.rule_id
                   LEFT JOIN lookout_sources s ON s.id=r.source_id
                   LEFT JOIN users u ON u.id=cr.user_id
                   WHERE """ + where + " ORDER BY cr.id DESC LIMIT ? OFFSET ?",
                (*params, page_size, offset),
            ).fetchall()
        return [dict(row) for row in rows], total

    @staticmethod
    def get_task_progress(task_id: int) -> dict | None:
        with connection_scope() as connection:
            row = connection.execute(
                """SELECT cr.*,r.name AS rule_name,s.name AS source_name,u.username AS operator_name
                   FROM collection_runs cr
                   LEFT JOIN collection_rules r ON r.id=cr.rule_id
                   LEFT JOIN lookout_sources s ON s.id=r.source_id
                   LEFT JOIN users u ON u.id=cr.user_id
                   WHERE cr.id=?""",
                (int(task_id),),
            ).fetchone()
            if not row:
                return None
            logs = connection.execute(
                """SELECT * FROM (
                       SELECT * FROM collection_run_logs WHERE run_id=? ORDER BY id DESC LIMIT 80
                   ) ORDER BY id""",
                (task_id,),
            ).fetchall()
            results = connection.execute(
                "SELECT * FROM collection_results WHERE run_id=? ORDER BY id LIMIT 100",
                (task_id,),
            ).fetchall()
        payload = dict(row)
        payload["logs"] = [dict(item) for item in logs]
        payload["items"] = [dict(item) for item in results]
        payload["terminal"] = payload["status"] in TERMINAL_STATUSES
        return payload

    @classmethod
    def retry_failed_task(cls, task_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                """UPDATE collection_runs
                   SET status='pending',processed_pages=0,failed_count=0,progress=0,
                       retry_count=retry_count+1,error_message='',started_at=NULL,
                       finished_at=NULL,cancelled_at=NULL,updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND status IN ('failed','partial','cancelled')""",
                (int(task_id),),
            )
            connection.commit()
        if cursor.rowcount == 1:
            cls._log(task_id, "info", "retry", "任务已重置，等待重新执行")
            return True
        return False

    @classmethod
    def cancel_task(cls, task_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                """UPDATE collection_runs
                   SET status='cancelled',cancelled_at=CURRENT_TIMESTAMP,
                       finished_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP,
                       error_message='任务由管理员取消'
                   WHERE id=? AND status IN ('pending','running')""",
                (int(task_id),),
            )
            connection.commit()
        if cursor.rowcount == 1:
            cls._log(task_id, "warning", "cancelled", "任务由管理员取消")
            return True
        return False

    @classmethod
    def recover_interrupted(cls) -> list[int]:
        """把服务中断时仍为 running 的任务恢复为 pending，供启动后自动续跑。"""
        with connection_scope() as connection:
            rows = connection.execute(
                "SELECT id FROM collection_runs WHERE status='running' ORDER BY id"
            ).fetchall()
            task_ids = [int(row["id"]) for row in rows]
            if task_ids:
                connection.execute(
                    """UPDATE collection_runs
                       SET status='pending',retry_count=retry_count+1,
                           error_message='服务重启后自动恢复',updated_at=CURRENT_TIMESTAMP
                       WHERE status='running'"""
                )
                connection.commit()
        for task_id in task_ids:
            cls._log(task_id, "warning", "recovered", "检测到服务中断，任务已恢复并等待续跑")
        return task_ids

    @classmethod
    def resume_pending_tasks(cls, limit: int = 50) -> list[int]:
        with connection_scope() as connection:
            rows = connection.execute(
                "SELECT id FROM collection_runs WHERE status='pending' ORDER BY id LIMIT ?",
                (min(200, max(1, int(limit))),),
            ).fetchall()
        task_ids = [int(row["id"]) for row in rows]
        for task_id in task_ids:
            cls.schedule(task_id)
        return task_ids

    @staticmethod
    def batch_delete_items(item_ids: list[int]) -> int:
        ids: list[int] = []
        for item_id in item_ids[:1000]:
            try:
                parsed = int(item_id)
            except (TypeError, ValueError):
                continue
            if parsed > 0 and parsed not in ids:
                ids.append(parsed)
        if not ids:
            return 0
        with connection_scope() as connection:
            placeholders = ",".join("?" for _ in ids)
            cursor = connection.execute(
                f"DELETE FROM warehouse_items WHERE id IN ({placeholders})", ids
            )
            connection.commit()
        return int(cursor.rowcount)

    @classmethod
    def batch_mark_deep_collection(
        cls, item_ids: list[int], employee_id: int | None = None
    ) -> int:
        created = 0
        for item_id in item_ids[:500]:
            if cls.create_deep_task(int(item_id), employee_id=employee_id):
                created += 1
        return created
