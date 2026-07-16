"""舆情安全后端 Repository。"""

from __future__ import annotations

import json
import math
import re

from app.models.db import connection_scope

DEFAULT_SENSITIVE_WORDS = [
    ("敏感词示例1", "default", 2, "示例敏感词"),
    ("敏感词示例2", "default", 3, "示例敏感词"),
    ("测试敏感词", "test", 1, "测试用"),
]


class SensitiveWordRepository:
    @staticmethod
    def list_words(keyword: str = "", category: str = "", page: int = 1, page_size: int = 20):
        pattern = f"%{keyword}%"
        clauses = ["a.source_type = 'chat'"]
        params = []
        if keyword:
            clauses.append("word LIKE ?")
            params.append(pattern)
        if category:
            clauses.append("category = ?")
            params.append(category)
        
        where_sql = " AND ".join(clauses) if clauses else "1=1"
        
        with connection_scope() as connection:
            total_row = connection.execute(
                f"SELECT COUNT(*) AS total FROM sensitive_words WHERE {where_sql}", params
            ).fetchone()
            total = int(total_row["total"])
            offset = (page - 1) * page_size
            rows = connection.execute(
                f"SELECT * FROM sensitive_words WHERE {where_sql} ORDER BY level DESC, word LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            ).fetchall()
        
        total_pages = max(1, math.ceil(total / page_size))
        return [dict(row) for row in rows], {
            "page": page, "page_size": page_size, "total": total, "total_pages": total_pages
        }

    @staticmethod
    def get(word_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT * FROM sensitive_words WHERE id = ?", (word_id,)
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def create(word: str, category: str = "default", level: int = 1, description: str = "", user_id: int = None):
        try:
            with connection_scope() as connection:
                connection.execute(
                    """
                    INSERT INTO sensitive_words (word, category, level, description, created_by)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (word, category, level, description, user_id),
                )
                connection.commit()
            return True
        except Exception:
            return False

    @staticmethod
    def update(word_id: int, word: str, category: str, level: int, description: str, enabled: bool):
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    UPDATE sensitive_words SET word = ?, category = ?, level = ?, description = ?,
                                               enabled = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (word, category, level, description, int(enabled), word_id),
                )
                connection.commit()
            return cursor.rowcount == 1
        except Exception:
            return False

    @staticmethod
    def delete(word_id: int):
        with connection_scope() as connection:
            cursor = connection.execute(
                "DELETE FROM sensitive_words WHERE id = ?", (word_id,)
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def search(content: str) -> list[dict]:
        with connection_scope() as connection:
            rows = connection.execute(
                "SELECT id, word, category, level FROM sensitive_words WHERE enabled = 1"
            ).fetchall()
        
        results = []
        for row in rows:
            word = row["word"]
            if re.search(re.escape(word), content, re.IGNORECASE):
                results.append(dict(row))
        return results

    @staticmethod
    def seed_defaults(connection) -> None:
        for word, category, level, description in DEFAULT_SENSITIVE_WORDS:
            connection.execute(
                """
                INSERT OR IGNORE INTO sensitive_words (word, category, level, description)
                VALUES (?, ?, ?, ?)
                """,
                (word, category, level, description),
            )


class OpinionAlertRepository:
    @staticmethod
    def list_alerts(
        status: str = "",
        risk_level: str = "",
        user_id: int = None,
        page: int = 1,
        page_size: int = 20,
    ):
        clauses = ["a.source_type = ?"]
        params = ["chat"]
        if status:
            clauses.append("a.status = ?")
            params.append(status)
        if risk_level:
            clauses.append("a.risk_level = ?")
            params.append(risk_level)
        if user_id:
            clauses.append("a.user_id = ?")
            params.append(user_id)
        
        where_sql = " AND ".join(clauses) if clauses else "1=1"
        
        with connection_scope() as connection:
            total_row = connection.execute(
                f"SELECT COUNT(*) AS total FROM opinion_alerts a WHERE {where_sql}", params
            ).fetchone()
            total = int(total_row["total"])
            offset = (page - 1) * page_size
            rows = connection.execute(
                f"""
                SELECT a.*, u.username AS user_name, h.username AS handler_name
                FROM opinion_alerts a
                LEFT JOIN users u ON u.id = a.user_id
                LEFT JOIN users h ON h.id = a.handled_by
                WHERE {where_sql}
                ORDER BY a.created_at DESC LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()
        
        total_pages = max(1, math.ceil(total / page_size))
        return [dict(row) for row in rows], {
            "page": page, "page_size": page_size, "total": total, "total_pages": total_pages
        }

    @staticmethod
    def get(alert_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT a.*, u.username AS user_name,
                       handler.username AS handled_by_name
                FROM opinion_alerts a
                LEFT JOIN users u ON u.id = a.user_id
                LEFT JOIN users handler ON handler.id = a.handled_by
                WHERE a.id = ? AND a.source_type='chat'
                """,
                (alert_id,),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def create(
        source_type: str,
        source_id: int,
        user_id: int,
        content: str,
        matched_words: list[dict],
        risk_level: str = "low",
        ai_analysis: str = "",
        content_hash: str = "",
        metadata: dict | None = None,
    ):
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO opinion_alerts
                    (source_type, source_id, user_id, title, content, excerpt,
                     matched_words, risk_level, ai_analysis, content_hash, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_type,
                        source_id,
                        user_id,
                        content[:80],
                        content,
                        content[:500],
                        json.dumps(matched_words, ensure_ascii=False),
                        risk_level,
                        ai_analysis,
                        content_hash,
                        json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                connection.commit()
                if cursor.rowcount:
                    return int(cursor.lastrowid)
                row = connection.execute(
                    """SELECT id FROM opinion_alerts
                       WHERE source_type=? AND source_id=? AND content_hash=?""",
                    (source_type, source_id, content_hash),
                ).fetchone()
            return int(row["id"]) if row else 0
        except Exception:
            return 0

    @staticmethod
    def update_status(alert_id: int, status: str, handled_by: int, handle_note: str = ""):
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                UPDATE opinion_alerts
                SET status = ?, handled_by = ?, handle_note = ?, handled_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, handled_by, handle_note, alert_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def delete(alert_id: int):
        with connection_scope() as connection:
            cursor = connection.execute(
                "DELETE FROM opinion_alerts WHERE id = ?", (alert_id,)
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def count_by_status():
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM opinion_alerts
                WHERE source_type='chat'
                GROUP BY status
                """
            ).fetchall()
        return {row["status"]: row["count"] for row in rows}

    @staticmethod
    def count_by_risk():
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT risk_level, COUNT(*) AS count
                FROM opinion_alerts
                WHERE source_type='chat'
                GROUP BY risk_level
                """
            ).fetchall()
        return {row["risk_level"]: row["count"] for row in rows}


class AuditLogRepository:
    @staticmethod
    def create(
        action_type: str,
        resource_type: str,
        resource_id: int = None,
        user_id: int = None,
        user_name: str = "",
        ip_address: str = "",
        action_before: dict = None,
        action_after: dict = None,
        detail: str = "",
        success: bool = True,
        error_message: str = "",
    ):
        try:
            with connection_scope() as connection:
                connection.execute(
                    """
                    INSERT INTO audit_logs
                    (action_type, resource_type, resource_id, user_id, user_name, ip_address,
                     action_before, action_after, detail, success, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        action_type,
                        resource_type,
                        resource_id,
                        user_id,
                        user_name,
                        ip_address,
                        json.dumps(action_before or {}, ensure_ascii=False),
                        json.dumps(action_after or {}, ensure_ascii=False),
                        detail,
                        int(success),
                        error_message,
                    ),
                )
                connection.commit()
            return True
        except Exception:
            return False

    @staticmethod
    def list_logs(
        action_type: str = "",
        user_id: int = None,
        resource_type: str = "",
        resource_id: int | None = None,
        start_date: str = "",
        end_date: str = "",
        page: int = 1,
        page_size: int = 20,
    ):
        clauses = []
        params = []
        if action_type:
            clauses.append("action_type = ?")
            params.append(action_type)
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if resource_type:
            clauses.append("resource_type = ?")
            params.append(resource_type)
        if resource_id:
            clauses.append("resource_id = ?")
            params.append(resource_id)
        if start_date:
            clauses.append("date(created_at) >= date(?)")
            params.append(start_date)
        if end_date:
            clauses.append("date(created_at) <= date(?)")
            params.append(end_date)
        
        where_sql = " AND ".join(clauses) if clauses else "1=1"
        
        with connection_scope() as connection:
            total_row = connection.execute(
                f"SELECT COUNT(*) AS total FROM audit_logs WHERE {where_sql}", params
            ).fetchone()
            total = int(total_row["total"])
            offset = (page - 1) * page_size
            rows = connection.execute(
                f"""
                SELECT * FROM audit_logs
                WHERE {where_sql}
                ORDER BY created_at DESC LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()
        
        total_pages = max(1, math.ceil(total / page_size))
        return [dict(row) for row in rows], {
            "page": page, "page_size": page_size, "total": total, "total_pages": total_pages
        }
