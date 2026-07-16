"""用户侧对话与消息 Repository。"""

from __future__ import annotations

import json
import re

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
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                INSERT INTO user_messages
                    (conversation_id, role, content, content_type, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    conversation_id, role, content, content_type,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            connection.execute(
                "UPDATE user_conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (conversation_id,),
            )
            connection.commit()
            return int(cursor.lastrowid)

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
