"""用户侧对话与消息 Repository。"""

from __future__ import annotations

import json
import re
from datetime import datetime

from app.models.db import connection_scope


def _conversation(row) -> dict | None:
    if row is None:
        return None
    return dict(row)


def _message(row) -> dict:
    item = dict(row)
    try:
        item["metadata"] = json.loads(item.get("metadata") or "{}")
    except json.JSONDecodeError:
        item["metadata"] = {}
    return item


class ConversationRepository:
    @staticmethod
    def title_from_prompt(prompt: str) -> str:
        title = re.sub(r"^\s*[/@][^\s]+\s*", "", prompt).strip()
        title = re.sub(r"\s+", " ", title)
        if not title:
            title = re.sub(r"\s+", " ", prompt).strip()
        return (title[:22] + "…") if len(title) > 22 else (title or "新对话")

    @staticmethod
    def list_for_user(user_id: int, limit: int = 80) -> list[dict]:
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT c.*, m.name AS model_name, e.name AS employee_name,
                       (SELECT COUNT(*) FROM user_messages um
                        WHERE um.conversation_id = c.id) AS message_count
                FROM user_conversations c
                LEFT JOIN model_configs m ON m.id = c.model_id
                LEFT JOIN digital_employees e ON e.id = c.employee_id
                WHERE c.user_id = ?
                ORDER BY c.updated_at DESC, c.id DESC LIMIT ?
                """,
                (user_id, min(200, max(1, int(limit)))),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def create(
        user_id: int, title: str, model_id: int | None = None,
        employee_id: int | None = None,
    ) -> int:
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                INSERT INTO user_conversations (user_id, title, model_id, employee_id)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, title.strip()[:80] or "新对话", model_id, employee_id),
            )
            connection.commit()
            return int(cursor.lastrowid)

    @staticmethod
    def get_for_user(conversation_id: int, user_id: int) -> dict | None:
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT c.*, m.name AS model_name, e.name AS employee_name
                FROM user_conversations c
                LEFT JOIN model_configs m ON m.id = c.model_id
                LEFT JOIN digital_employees e ON e.id = c.employee_id
                WHERE c.id = ? AND c.user_id = ?
                """,
                (conversation_id, user_id),
            ).fetchone()
        return _conversation(row)

    @staticmethod
    def messages(conversation_id: int, user_id: int) -> list[dict]:
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT um.* FROM user_messages um
                JOIN user_conversations c ON c.id = um.conversation_id
                WHERE um.conversation_id = ? AND c.user_id = ?
                ORDER BY um.id
                """,
                (conversation_id, user_id),
            ).fetchall()
        return [_message(row) for row in rows]

    @staticmethod
    def add_message(
        conversation_id: int, role: str, content: str,
        content_type: str = "text", metadata: dict | None = None,
    ) -> int:
        metadata = metadata or {}
        usage = metadata.get("usage") if isinstance(metadata.get("usage"), dict) else {}
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                INSERT INTO user_messages
                    (conversation_id, role, content, content_type, metadata,
                     latency_ms,token_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id, role, content, content_type,
                    json.dumps(metadata, ensure_ascii=False),
                    max(0, int(usage.get("latency_ms") or 0)),
                    max(0, int(usage.get("total_tokens") or 0)),
                ),
            )
            connection.execute(
                "UPDATE user_conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (conversation_id,),
            )
            connection.commit()
            return int(cursor.lastrowid)

    @staticmethod
    def update_message_security(message_id: int, analysis: dict) -> bool:
        matched = analysis.get("matched_words") or []
        with connection_scope() as connection:
            cursor = connection.execute(
                """UPDATE user_messages SET risk_level=?,matched_words=? WHERE id=?""",
                (
                    str(analysis.get("risk_level") or "low"),
                    json.dumps(matched, ensure_ascii=False, separators=(",", ":")),
                    int(message_id),
                ),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def update_context(
        conversation_id: int, user_id: int,
        model_id: int | None, employee_id: int | None,
    ) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                UPDATE user_conversations
                SET model_id=?, employee_id=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND user_id=?
                """,
                (model_id, employee_id, conversation_id, user_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def delete(conversation_id: int, user_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                "DELETE FROM user_conversations WHERE id=? AND user_id=?",
                (conversation_id, user_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def _list_all_for_admin(user_id: int | None, keyword: str = "", page: int = 1, page_size: int = 20) -> list[dict]:
        rows, _ = ConversationRepository.admin_list(
            user_id=user_id, keyword=keyword, page=page, page_size=page_size
        )
        return rows

    @staticmethod
    def admin_list(
        *,
        user_id: int | None = None,
        keyword: str = "",
        start_date: str = "",
        end_date: str = "",
        model_id: int | None = None,
        employee_id: int | None = None,
        status: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        page = max(1, int(page or 1))
        page_size = min(100, max(1, int(page_size or 20)))
        clauses = ["(?='' OR c.title LIKE ? OR u.username LIKE ?)"]
        pattern = f"%{keyword.strip()}%"
        params: list[object] = [keyword.strip(), pattern, pattern]
        if user_id:
            clauses.append("c.user_id=?")
            params.append(int(user_id))
        if start_date:
            clauses.append("date(c.created_at)>=date(?)")
            params.append(start_date)
        if end_date:
            clauses.append("date(c.created_at)<=date(?)")
            params.append(end_date)
        if model_id:
            clauses.append("c.model_id=?")
            params.append(int(model_id))
        if employee_id:
            clauses.append("c.employee_id=?")
            params.append(int(employee_id))
        if status in {"active", "archived"}:
            clauses.append("c.status=?")
            params.append(status)
        where_sql = " AND ".join(clauses)
        with connection_scope() as connection:
            total = int(
                connection.execute(
                    """SELECT COUNT(*) AS count FROM user_conversations c
                       JOIN users u ON u.id=c.user_id WHERE """ + where_sql,
                    params,
                ).fetchone()["count"]
            )
            rows = connection.execute(
                f"""
                SELECT c.*, m.name AS model_name, e.name AS employee_name,
                       u.username AS user_name,
                       (SELECT COUNT(*) FROM user_messages um
                        WHERE um.conversation_id = c.id) AS message_count,
                       (SELECT COALESCE(SUM(um.token_count),0) FROM user_messages um
                        WHERE um.conversation_id=c.id) AS total_tokens,
                       (SELECT COALESCE(MAX(um.latency_ms),0) FROM user_messages um
                        WHERE um.conversation_id=c.id) AS max_latency_ms,
                       (SELECT CASE MAX(CASE um.risk_level WHEN 'critical' THEN 4
                            WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END)
                            WHEN 4 THEN 'critical' WHEN 3 THEN 'high'
                            WHEN 2 THEN 'medium' ELSE 'low' END
                        FROM user_messages um WHERE um.conversation_id=c.id) AS risk_level
                FROM user_conversations c
                LEFT JOIN model_configs m ON m.id = c.model_id
                LEFT JOIN digital_employees e ON e.id = c.employee_id
                LEFT JOIN users u ON u.id = c.user_id
                WHERE {where_sql}
                ORDER BY c.updated_at DESC, c.id DESC LIMIT ? OFFSET ?
                """,
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        return [dict(row) for row in rows], total

    @staticmethod
    def _get_for_admin(conversation_id: int) -> dict | None:
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT c.*, m.name AS model_name, e.name AS employee_name,
                       u.username AS user_name
                FROM user_conversations c
                LEFT JOIN model_configs m ON m.id = c.model_id
                LEFT JOIN digital_employees e ON e.id = c.employee_id
                LEFT JOIN users u ON u.id = c.user_id
                WHERE c.id = ?
                """,
                (conversation_id,),
            ).fetchone()
        return _conversation(row)

    @staticmethod
    def _messages_for_admin(conversation_id: int) -> list[dict]:
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT um.* FROM user_messages um
                WHERE um.conversation_id = ?
                ORDER BY um.id
                """,
                (conversation_id,),
            ).fetchall()
        return [_message(row) for row in rows]

    @staticmethod
    def _delete_for_admin(conversation_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                "DELETE FROM user_conversations WHERE id=?",
                (conversation_id,),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def batch_delete_for_admin(conversation_ids: list[int]) -> int:
        ids = sorted({item for item in conversation_ids if item > 0})[:500]
        if not ids:
            return 0
        with connection_scope() as connection:
            cursor = connection.execute(
                f"DELETE FROM user_conversations WHERE id IN ({','.join('?' for _ in ids)})",
                ids,
            )
            connection.commit()
        return int(cursor.rowcount)

    @staticmethod
    def set_archived(conversation_ids: list[int], archived: bool) -> int:
        ids = sorted({item for item in conversation_ids if item > 0})[:500]
        if not ids:
            return 0
        with connection_scope() as connection:
            cursor = connection.execute(
                f"""UPDATE user_conversations SET status=?,archived_at=?,
                    updated_at=CURRENT_TIMESTAMP
                    WHERE id IN ({','.join('?' for _ in ids)})""",
                (
                    "archived" if archived else "active",
                    datetime.now().isoformat(timespec="seconds") if archived else None,
                    *ids,
                ),
            )
            connection.commit()
        return int(cursor.rowcount)
