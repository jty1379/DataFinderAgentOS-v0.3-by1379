"""深度采集任务、日志与结果 Repository。"""

from __future__ import annotations

import json
import sqlite3

from app.models.db import connection_scope


def _decode(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    if "metadata" in item:
        try:
            item["metadata"] = json.loads(item.get("metadata") or "{}")
        except json.JSONDecodeError:
            item["metadata"] = {}
    for key in ("is_update", "employee_enabled"):
        if key in item:
            item[key] = bool(item[key])
    return item


class DeepCollectionRepository:
    @staticmethod
    def recover_interrupted() -> int:
        with connection_scope() as connection:
            rows = connection.execute(
                "SELECT id FROM deep_collection_tasks WHERE status IN ('pending', 'running')"
            ).fetchall()
            for row in rows:
                connection.execute(
                    """UPDATE deep_collection_tasks SET status='failed', progress=100,
                       current_step='任务中断', error_message='服务重启，任务已中断',
                       finished_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (row["id"],),
                )
                connection.execute(
                    "INSERT INTO deep_collection_logs(task_id, level, step, message) VALUES (?, 'error', '任务中断', '服务重启，未完成任务已安全终止')",
                    (row["id"],),
                )
            connection.commit()
        return len(rows)

    @staticmethod
    def create_tasks(item_ids, employee_id: int, user_id: int | None, update: bool = False) -> tuple[list[int], list[int]]:
        clean: list[int] = []
        for value in item_ids or []:
            try:
                item_id = int(value)
            except (TypeError, ValueError):
                continue
            if item_id > 0 and item_id not in clean:
                clean.append(item_id)
        task_ids: list[int] = []
        skipped: list[int] = []
        with connection_scope() as connection:
            for item_id in clean[:50]:
                item = connection.execute(
                    "SELECT id, deep_collected FROM warehouse_items WHERE id=?", (item_id,)
                ).fetchone()
                active = connection.execute(
                    "SELECT id FROM deep_collection_tasks WHERE warehouse_item_id=? AND status IN ('pending','running') LIMIT 1",
                    (item_id,),
                ).fetchone()
                if item is None or active or (item["deep_collected"] and not update):
                    skipped.append(item_id)
                    continue
                try:
                    cursor = connection.execute(
                        """INSERT INTO deep_collection_tasks
                           (warehouse_item_id, employee_id, is_update, started_by)
                           VALUES (?, ?, ?, ?)""",
                        (item_id, employee_id, int(bool(update)), user_id),
                    )
                except sqlite3.IntegrityError:
                    skipped.append(item_id)
                    continue
                task_id = int(cursor.lastrowid)
                connection.execute(
                    "INSERT INTO deep_collection_logs(task_id, step, message) VALUES (?, '等待调度', '任务已创建，等待采集专员接收')",
                    (task_id,),
                )
                task_ids.append(task_id)
            connection.commit()
        return task_ids, skipped

    @staticmethod
    def update_progress(task_id: int, progress: int, step: str, message: str = "", level: str = "info") -> None:
        progress = min(100, max(0, int(progress)))
        with connection_scope() as connection:
            connection.execute(
                """UPDATE deep_collection_tasks SET status='running', progress=?,
                   current_step=?, started_at=COALESCE(started_at, CURRENT_TIMESTAMP)
                   WHERE id=? AND status IN ('pending','running')""",
                (progress, step[:80], task_id),
            )
            if message:
                connection.execute(
                    "INSERT INTO deep_collection_logs(task_id, level, step, message) VALUES (?, ?, ?, ?)",
                    (task_id, level if level in {"info", "success", "warning", "error"} else "info", step[:80], message[:1000]),
                )
            connection.commit()

    @staticmethod
    def complete(task_id: int, title: str, content: str, excerpt: str, metadata: dict) -> bool:
        content = content.strip()[:200000]
        with connection_scope() as connection:
            task = connection.execute(
                "SELECT warehouse_item_id, employee_id FROM deep_collection_tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            if task is None:
                return False
            connection.execute(
                """INSERT OR REPLACE INTO deep_collection_results
                   (task_id, warehouse_item_id, employee_id, title, content, excerpt, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (task_id, task["warehouse_item_id"], task["employee_id"], title[:500], content, excerpt[:2000], json.dumps(metadata, ensure_ascii=False)),
            )
            connection.execute(
                """UPDATE warehouse_items SET content=?, deep_collected=1,
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (content, task["warehouse_item_id"]),
            )
            connection.execute(
                """UPDATE deep_collection_tasks SET status='success', progress=100,
                   current_step='采集完成', error_message='', finished_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (task_id,),
            )
            connection.execute(
                "INSERT INTO deep_collection_logs(task_id, level, step, message) VALUES (?, 'success', '采集完成', '正文与结构化元数据已持久化到数据仓库')",
                (task_id,),
            )
            connection.commit()
        return True

    @staticmethod
    def fail(task_id: int, message: str) -> None:
        message = str(message).strip()[:500] or "深度采集失败"
        with connection_scope() as connection:
            connection.execute(
                """UPDATE deep_collection_tasks SET status='failed', progress=100,
                   current_step='执行失败', error_message=?, finished_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (message, task_id),
            )
            connection.execute(
                "INSERT INTO deep_collection_logs(task_id, level, step, message) VALUES (?, 'error', '执行失败', ?)",
                (task_id, message),
            )
            connection.commit()

    @staticmethod
    def detail(task_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                """SELECT t.*, w.title AS item_title, w.url AS item_url,
                          d.name AS employee_name, d.mention AS employee_mention,
                          d.description AS employee_description, d.enabled AS employee_enabled,
                          r.id AS result_id, r.title AS result_title, r.excerpt,
                          r.content AS result_content, r.metadata
                   FROM deep_collection_tasks t
                   JOIN warehouse_items w ON w.id=t.warehouse_item_id
                   LEFT JOIN digital_employees d ON d.id=t.employee_id
                   LEFT JOIN deep_collection_results r ON r.task_id=t.id
                   WHERE t.id=?""",
                (task_id,),
            ).fetchone()
            logs = connection.execute(
                "SELECT id, level, step, message, created_at FROM deep_collection_logs WHERE task_id=? ORDER BY id",
                (task_id,),
            ).fetchall()
        item = _decode(row)
        if item is not None:
            item["logs"] = [dict(log) for log in logs]
        return item

    @staticmethod
    def latest_result(item_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                """SELECT r.*, d.name AS employee_name, d.mention AS employee_mention,
                          t.is_update, w.url AS item_url, w.source_name
                   FROM deep_collection_results r
                   JOIN deep_collection_tasks t ON t.id=r.task_id
                   JOIN warehouse_items w ON w.id=r.warehouse_item_id
                   LEFT JOIN digital_employees d ON d.id=r.employee_id
                   WHERE r.warehouse_item_id=? ORDER BY r.id DESC LIMIT 1""",
                (item_id,),
            ).fetchone()
        return _decode(row)
