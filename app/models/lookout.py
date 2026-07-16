"""瞭望采集批次与结果 Repository。"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from app.models.db import connection_scope


def _result(row) -> dict:
    item = dict(row)
    raw = item.get("raw_data", "{}")
    try:
        item["raw_data"] = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except json.JSONDecodeError:
        item["raw_data"] = {}
    return item


class CollectionRepository:
    @staticmethod
    def create_run(
        rule_id: int,
        keyword: str,
        page: int = 1,
        page_size: int = 12,
        user_id: int | None = None,
        request_url: str = "",
    ) -> int:
        keyword = keyword.strip()
        if not keyword or len(keyword) > 100:
            raise ValueError("采集关键词需为 1—100 个字符")
        page = max(1, int(page or 1))
        page_size = min(100, max(1, int(page_size or 12)))
        with connection_scope() as connection:
            rule = connection.execute(
                """
                SELECT 1 FROM collection_rules r
                JOIN lookout_sources s ON s.id = r.source_id
                WHERE r.id = ? AND r.enabled = 1 AND s.enabled = 1
                """,
                (rule_id,),
            ).fetchone()
            if rule is None:
                raise ValueError("采集规则不存在或已停用")
            cursor = connection.execute(
                """
                INSERT INTO collection_runs
                    (rule_id, user_id, keyword, page_number, page_size,
                     request_url, status)
                VALUES (?, ?, ?, ?, ?, ?, 'running')
                """,
                (rule_id, user_id, keyword, page, page_size, request_url[:2000]),
            )
            connection.commit()
            return int(cursor.lastrowid)

    @staticmethod
    def set_request_url(run_id: int, request_url: str) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                "UPDATE collection_runs SET request_url = ? WHERE id = ?",
                (request_url[:2000], run_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def save_results(run_id: int, items: list[dict]) -> list[dict]:
        with connection_scope() as connection:
            run = connection.execute(
                "SELECT rule_id FROM collection_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise ValueError("采集批次不存在")
            accepted_urls: list[str] = []
            for item in items[:100]:
                title = str(item.get("title", "")).strip()[:300]
                url = str(item.get("url", "")).strip()[:2000]
                parsed = urlsplit(url)
                if not title or parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                    continue
                raw_data = item.get("raw_data", item)
                try:
                    raw_json = json.dumps(
                        raw_data if isinstance(raw_data, dict) else {},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                except (TypeError, ValueError):
                    raw_json = "{}"
                connection.execute(
                    """
                    INSERT OR IGNORE INTO collection_results
                        (run_id, rule_id, title, url, summary, source_name,
                         published_at, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        run["rule_id"],
                        title,
                        url,
                        str(item.get("summary", "")).strip()[:2000],
                        str(item.get("source_name", "")).strip()[:100],
                        str(item.get("published_at", "")).strip()[:100],
                        raw_json,
                    ),
                )
                accepted_urls.append(url)
            count = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM collection_results WHERE run_id = ?",
                    (run_id,),
                ).fetchone()["count"]
            )
            connection.execute(
                """
                UPDATE collection_runs
                SET status = 'success', result_count = ?, error_message = '',
                    finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (count, run_id),
            )
            rows = connection.execute(
                "SELECT * FROM collection_results WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
            connection.commit()
        return [_result(row) for row in rows]

    @staticmethod
    def fail_run(run_id: int, message: str) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                UPDATE collection_runs
                SET status = 'failed', error_message = ?, finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (message.strip()[:500], run_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def finish_run(run_id: int, result_count: int | None = None) -> bool:
        """显式完成批次的兼容接口；save_results 已会自动调整状态。"""
        with connection_scope() as connection:
            if result_count is None:
                result_count = int(
                    connection.execute(
                        "SELECT COUNT(*) AS count FROM collection_results WHERE run_id = ?",
                        (run_id,),
                    ).fetchone()["count"]
                )
            cursor = connection.execute(
                """
                UPDATE collection_runs
                SET status = 'success', result_count = ?, error_message = '',
                    finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP)
                WHERE id = ?
                """,
                (max(0, int(result_count)), run_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def get_run(run_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT cr.*, r.name AS rule_name, s.name AS source_name
                FROM collection_runs cr
                LEFT JOIN collection_rules r ON r.id = cr.rule_id
                LEFT JOIN lookout_sources s ON s.id = r.source_id
                WHERE cr.id = ?
                """,
                (run_id,),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_runs(limit: int = 5) -> list[dict]:
        limit = min(50, max(1, int(limit or 5)))
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT cr.*, r.name AS rule_name, s.name AS source_name,
                       u.username AS operator_name
                FROM collection_runs cr
                LEFT JOIN collection_rules r ON r.id = cr.rule_id
                LEFT JOIN lookout_sources s ON s.id = r.source_id
                LEFT JOIN users u ON u.id = cr.user_id
                ORDER BY cr.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def list_results(
        run_id: int, page: int = 1, page_size: int = 12
    ) -> tuple[list[dict], int]:
        page = max(1, int(page or 1))
        page_size = min(100, max(1, int(page_size or 12)))
        offset = (page - 1) * page_size
        with connection_scope() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM collection_results WHERE run_id = ?",
                    (run_id,),
                ).fetchone()["count"]
            )
            rows = connection.execute(
                """
                SELECT * FROM collection_results
                WHERE run_id = ? ORDER BY id LIMIT ? OFFSET ?
                """,
                (run_id, page_size, offset),
            ).fetchall()
        return [_result(row) for row in rows], total
