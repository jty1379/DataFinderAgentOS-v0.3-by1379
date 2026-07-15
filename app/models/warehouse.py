"""数据仓库 Repository。"""

from __future__ import annotations

import json

from app.models.db import connection_scope


def _item(row) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    try:
        result["raw_data"] = json.loads(result.get("raw_data") or "{}")
    except json.JSONDecodeError:
        result["raw_data"] = {}
    result["deep_collected"] = bool(result["deep_collected"])
    return result


class WarehouseRepository:
    @staticmethod
    def import_results(result_ids, user_id: int | None) -> tuple[int, int]:
        ids: list[int] = []
        for value in result_ids or []:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0 and parsed not in ids:
                ids.append(parsed)
        if not ids:
            return 0, 0

        inserted = 0
        with connection_scope() as connection:
            for result_id in ids[:200]:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO warehouse_items
                        (source_result_id, rule_id, title, url, summary, source_name,
                         published_at, raw_data, created_by)
                    SELECT id, rule_id, title, url, summary, source_name,
                           published_at, raw_data, ?
                    FROM collection_results WHERE id = ?
                    """,
                    (user_id, result_id),
                )
                inserted += max(0, cursor.rowcount)
            connection.commit()
        return inserted, len(ids[:200]) - inserted

    @staticmethod
    def list(
        keyword: str = "",
        deep_status: str = "",
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[dict], int]:
        page = max(1, int(page or 1))
        page_size = min(100, max(1, int(page_size or 10)))
        offset = (page - 1) * page_size
        keyword = keyword.strip()
        pattern = f"%{keyword}%"
        clauses = ["(? = '' OR w.title LIKE ? OR w.summary LIKE ? OR w.source_name LIKE ?)"]
        params: list[object] = [keyword, pattern, pattern, pattern]
        normalized_status = deep_status.strip().lower()
        if normalized_status in {"1", "yes", "true", "deep", "completed"}:
            clauses.append("w.deep_collected = 1")
        elif normalized_status in {"0", "no", "false", "pending"}:
            clauses.append("w.deep_collected = 0")
        where = " AND ".join(clauses)
        with connection_scope() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM warehouse_items w WHERE " + where,
                    params,
                ).fetchone()["count"]
            )
            rows = connection.execute(
                """
                SELECT w.*, u.username AS creator_name, r.name AS rule_name
                FROM warehouse_items w
                LEFT JOIN users u ON u.id = w.created_by
                LEFT JOIN collection_rules r ON r.id = w.rule_id
                WHERE """
                + where
                + " ORDER BY w.id DESC LIMIT ? OFFSET ?",
                (*params, page_size, offset),
            ).fetchall()
        return [_item(row) for row in rows], total

    @staticmethod
    def get(item_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT w.*, u.username AS creator_name, r.name AS rule_name
                FROM warehouse_items w
                LEFT JOIN users u ON u.id = w.created_by
                LEFT JOIN collection_rules r ON r.id = w.rule_id
                WHERE w.id = ?
                """,
                (item_id,),
            ).fetchone()
        return _item(row)

    @staticmethod
    def delete(item_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute("DELETE FROM warehouse_items WHERE id = ?", (item_id,))
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def set_deep_collected(item_id: int, completed: bool, content: str = "") -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                UPDATE warehouse_items
                SET deep_collected = ?, content = CASE WHEN ? <> '' THEN ? ELSE content END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (int(bool(completed)), content, content[:100000], item_id),
            )
            connection.commit()
        return cursor.rowcount == 1
