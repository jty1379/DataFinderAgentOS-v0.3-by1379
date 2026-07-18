"""用户 Repository 与密码安全处理。"""

from __future__ import annotations

import hashlib
import math
import secrets
import sqlite3
from collections import Counter

from app.models.db import connection_scope
from app.models.rbac import RoleRepository

PBKDF2_ITERATIONS = 100_000


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    ).hex()


# Missing/disabled users take the same PBKDF2 path as existing users.  A fixed
# non-secret dummy record avoids generating a new salt on each attempt while
# keeping the observable cost independent of username existence.
_DUMMY_SALT = bytes.fromhex("9e2c4d449a8f6b93f207e46bd8fcf519")
_DUMMY_PASSWORD_HASH = _hash_password("invalid-authentication-record", _DUMMY_SALT)


def _public_user(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role_code"],
        "role_id": row["role_id"],
        "role_name": row["role_name"],
        "role_scope": row["role_scope"],
        "status": row["status"],
        "is_superadmin": bool(row["is_superadmin"]),
        "created_at": row["created_at"],
    }


USER_SELECT = """
    SELECT u.id, u.username, u.password_hash, u.salt, u.role_id, u.status,
           u.is_superadmin,
           u.created_at, r.code AS role_code, r.name AS role_name,
           r.access_scope AS role_scope, r.enabled AS role_enabled
    FROM users u JOIN roles r ON r.id = u.role_id
"""


def _pagination(page: int, page_size: int, total: int) -> dict:
    """Return one normalized pagination payload shared by the admin pages."""
    try:
        safe_size = int(page_size or 20)
    except (TypeError, ValueError):
        safe_size = 20
    safe_size = min(max(safe_size, 1), 100)
    total_pages = max(1, math.ceil(total / safe_size))
    try:
        safe_page = int(page or 1)
    except (TypeError, ValueError):
        safe_page = 1
    safe_page = min(max(safe_page, 1), total_pages)
    return {
        "page": safe_page,
        "page_size": safe_size,
        "total": total,
        "total_pages": total_pages,
        "has_prev": safe_page > 1,
        "has_next": safe_page < total_pages,
    }


class UserRepository:
    @staticmethod
    def create_user(username: str, password: str, role: str = "user", role_id: int | None = None) -> bool:
        selected_role = RoleRepository.get(role_id) if role_id else RoleRepository.get_by_code(role)
        if not selected_role or not selected_role["enabled"]:
            return False
        salt = secrets.token_bytes(16)
        password_hash = _hash_password(password, salt)
        try:
            with connection_scope() as connection:
                connection.execute(
                    """
                    INSERT INTO users (username, password_hash, salt, role, role_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (username, password_hash, salt.hex(), selected_role["access_scope"], selected_role["id"]),
                )
                connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    @staticmethod
    def authenticate(username: str, password: str):
        with connection_scope() as connection:
            row = connection.execute(
                USER_SELECT + " WHERE u.username = ? AND u.status = 'enabled' AND r.enabled = 1",
                (username,),
            ).fetchone()
        if row is None:
            computed = _hash_password(password, _DUMMY_SALT)
            secrets.compare_digest(computed, _DUMMY_PASSWORD_HASH)
            return None
        computed = _hash_password(password, bytes.fromhex(row["salt"]))
        if not secrets.compare_digest(computed, row["password_hash"]):
            return None
        return _public_user(row)

    @staticmethod
    def get_user_by_id(user_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                USER_SELECT + " WHERE u.id = ? AND u.status = 'enabled' AND r.enabled = 1",
                (user_id,),
            ).fetchone()
        return _public_user(row)

    @staticmethod
    def get_user_by_username(username: str):
        with connection_scope() as connection:
            row = connection.execute(USER_SELECT + " WHERE u.username = ?", (username,)).fetchone()
        return _public_user(row)

    @staticmethod
    def get_active_user_by_username(username: str):
        with connection_scope() as connection:
            row = connection.execute(
                USER_SELECT
                + " WHERE u.username = ? AND u.status = 'enabled' AND r.enabled = 1",
                (username,),
            ).fetchone()
        return _public_user(row)

    @staticmethod
    def list_users(keyword: str = "", role_id: int | None = None, status: str = "") -> list[dict]:
        pattern = f"%{keyword}%"
        clauses = ["(? = '' OR u.username LIKE ?)"]
        params: list[object] = [keyword, pattern]
        if role_id:
            clauses.append("u.role_id = ?")
            params.append(role_id)
        if status in {"enabled", "disabled"}:
            clauses.append("u.status = ?")
            params.append(status)
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT u.id, u.username, u.role_id, u.status, u.is_superadmin,
                       u.created_at, u.updated_at,
                       r.code AS role_code, r.name AS role_name, r.access_scope AS role_scope,
                       CASE WHEN fp.user_id IS NULL THEN 0 ELSE 1 END AS face_enrolled,
                       COALESCE(fp.enabled, 0) AS face_enabled
                FROM users u JOIN roles r ON r.id = u.role_id
                LEFT JOIN face_profiles fp ON fp.user_id=u.id
                WHERE """ + " AND ".join(clauses) + " ORDER BY u.id DESC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def paginate_users(
        keyword: str = "",
        role_id: int | None = None,
        status: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], dict]:
        """Return a filtered 20-per-page user list without changing ``list_users``."""
        pattern = f"%{keyword}%"
        clauses = ["(? = '' OR u.username LIKE ?)"]
        params: list[object] = [keyword, pattern]
        if role_id:
            clauses.append("u.role_id = ?")
            params.append(role_id)
        if status in {"enabled", "disabled"}:
            clauses.append("u.status = ?")
            params.append(status)
        where_sql = " AND ".join(clauses)
        with connection_scope() as connection:
            total_row = connection.execute(
                "SELECT COUNT(*) AS total FROM users u WHERE " + where_sql,
                params,
            ).fetchone()
            pagination = _pagination(page, page_size, int(total_row["total"]))
            rows = connection.execute(
                """
                SELECT u.id, u.username, u.role_id, u.status, u.is_superadmin,
                       u.created_at, u.updated_at,
                       r.code AS role_code, r.name AS role_name,
                       r.access_scope AS role_scope,
                       CASE WHEN fp.user_id IS NULL THEN 0 ELSE 1 END AS face_enrolled,
                       COALESCE(fp.enabled, 0) AS face_enabled
                FROM users u JOIN roles r ON r.id = u.role_id
                LEFT JOIN face_profiles fp ON fp.user_id=u.id
                WHERE """ + where_sql + " ORDER BY u.id DESC LIMIT ? OFFSET ?",
                [
                    *params,
                    pagination["page_size"],
                    (pagination["page"] - 1) * pagination["page_size"],
                ],
            ).fetchall()
        return [dict(row) for row in rows], pagination

    @staticmethod
    def batch_action(
        user_ids: list[int], action: str, actor_id: int
    ) -> tuple[int, str]:
        """Safely enable, disable or delete users in one explicit transaction.

        Only the enabled protected super administrator may invoke a write.  The
        protected account, current operator and last enabled administrator can
        never be disabled or deleted.  The message is suitable for direct UI
        feedback and includes skipped reasons.
        """
        if action not in {"enable", "disable", "delete"}:
            return 0, "不支持的批量操作"
        normalized: set[int] = set()
        for raw_user_id in user_ids:
            try:
                user_id = int(raw_user_id)
            except (TypeError, ValueError):
                continue
            if user_id > 0:
                normalized.add(user_id)
        normalized_ids = sorted(normalized)
        if not normalized_ids:
            return 0, "请选择要操作的用户"

        skipped: Counter[str] = Counter()
        changed = 0
        with connection_scope() as connection:
            # Acquire SQLite's write reservation before COUNT + UPDATE so two
            # concurrent administrators cannot both observe the same last
            # enabled administrator and then remove it.
            connection.execute("BEGIN IMMEDIATE")
            actor = connection.execute(
                """
                SELECT id FROM users
                WHERE id = ? AND is_superadmin = 1 AND status = 'enabled'
                """,
                (actor_id,),
            ).fetchone()
            if actor is None:
                return 0, "仅超级管理员可以执行批量操作"

            placeholders = ",".join("?" for _ in normalized_ids)
            rows = connection.execute(
                f"""
                SELECT u.id, u.status, u.is_superadmin, r.access_scope,
                       r.enabled AS role_enabled
                FROM users u JOIN roles r ON r.id = u.role_id
                WHERE u.id IN ({placeholders})
                ORDER BY u.id
                """,
                normalized_ids,
            ).fetchall()
            found_ids = {int(row["id"]) for row in rows}
            if len(found_ids) < len(normalized_ids):
                skipped["用户不存在"] += len(normalized_ids) - len(found_ids)

            admin_row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM users u JOIN roles r ON r.id = u.role_id
                WHERE u.status = 'enabled' AND r.enabled = 1
                      AND r.access_scope = 'admin'
                """
            ).fetchone()
            enabled_admins = int(admin_row["count"])

            for row in rows:
                user_id = int(row["id"])
                if row["is_superadmin"]:
                    skipped["超级管理员受保护"] += 1
                    continue
                if user_id == actor_id and action in {"disable", "delete"}:
                    skipped["不能操作当前账号"] += 1
                    continue

                removes_enabled_admin = (
                    action in {"disable", "delete"}
                    and row["status"] == "enabled"
                    and row["role_enabled"]
                    and row["access_scope"] == "admin"
                )
                if removes_enabled_admin and enabled_admins <= 1:
                    skipped["至少保留一名启用的管理员"] += 1
                    continue

                if action == "enable":
                    if row["status"] == "enabled":
                        skipped["账号已启用"] += 1
                        continue
                    cursor = connection.execute(
                        """
                        UPDATE users SET status = 'enabled', updated_at = CURRENT_TIMESTAMP
                        WHERE id = ? AND is_superadmin = 0
                        """,
                        (user_id,),
                    )
                elif action == "disable":
                    if row["status"] == "disabled":
                        skipped["账号已禁用"] += 1
                        continue
                    cursor = connection.execute(
                        """
                        UPDATE users SET status = 'disabled', updated_at = CURRENT_TIMESTAMP
                        WHERE id = ? AND is_superadmin = 0
                        """,
                        (user_id,),
                    )
                else:
                    cursor = connection.execute(
                        "DELETE FROM users WHERE id = ? AND is_superadmin = 0",
                        (user_id,),
                    )

                if cursor.rowcount == 1:
                    changed += 1
                    if removes_enabled_admin:
                        enabled_admins -= 1
                else:
                    skipped["操作未生效"] += 1

            connection.commit()

        details = "、".join(f"{reason} {count} 个" for reason, count in skipped.items())
        message = f"已处理 {changed} 个用户"
        if details:
            message += f"；已跳过：{details}"
        return changed, message

    @staticmethod
    def update_user(user_id: int, username: str, role_id: int, status: str, password: str = "") -> bool:
        selected_role = RoleRepository.get(role_id)
        if not selected_role or not selected_role["enabled"]:
            return False
        try:
            with connection_scope() as connection:
                protected = connection.execute(
                    "SELECT is_superadmin FROM users WHERE id = ?", (user_id,)
                ).fetchone()
                if protected is None or protected["is_superadmin"]:
                    return False
                if password:
                    salt = secrets.token_bytes(16)
                    cursor = connection.execute(
                        """
                        UPDATE users SET username = ?, role = ?, role_id = ?, status = ?,
                                         password_hash = ?, salt = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (username, selected_role["access_scope"], role_id, status,
                         _hash_password(password, salt), salt.hex(), user_id),
                    )
                else:
                    cursor = connection.execute(
                        """
                        UPDATE users SET username = ?, role = ?, role_id = ?, status = ?,
                                         updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (username, selected_role["access_scope"], role_id, status, user_id),
                    )
                connection.commit()
            return cursor.rowcount == 1
        except sqlite3.IntegrityError:
            return False

    @staticmethod
    def delete_user(user_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                "DELETE FROM users WHERE id = ? AND is_superadmin = 0", (user_id,)
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def get_superadmin():
        with connection_scope() as connection:
            row = connection.execute(
                USER_SELECT + " WHERE u.is_superadmin = 1 LIMIT 1"
            ).fetchone()
        return _public_user(row)

    @staticmethod
    def change_superadmin_password(
        user_id: int, current_password: str, new_password: str
    ) -> bool:
        """Change only the protected password after verifying the current secret."""
        if not 6 <= len(new_password) <= 64:
            return False
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT password_hash, salt
                FROM users
                WHERE id = ? AND is_superadmin = 1 AND status = 'enabled'
                """,
                (user_id,),
            ).fetchone()
            if row is None:
                return False
            current_hash = _hash_password(current_password, bytes.fromhex(row["salt"]))
            if not secrets.compare_digest(current_hash, row["password_hash"]):
                return False
            salt = secrets.token_bytes(16)
            cursor = connection.execute(
                """
                UPDATE users
                SET password_hash = ?, salt = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND is_superadmin = 1
                """,
                (_hash_password(new_password, salt), salt.hex(), user_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def is_enabled_admin(user_id: int) -> bool:
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM users u JOIN roles r ON r.id = u.role_id
                WHERE u.id = ? AND u.status = 'enabled' AND r.enabled = 1
                      AND r.access_scope = 'admin'
                """,
                (user_id,),
            ).fetchone()
        return row is not None

    @staticmethod
    def count_enabled_admins() -> int:
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count FROM users u JOIN roles r ON r.id = u.role_id
                WHERE u.status = 'enabled' AND r.enabled = 1 AND r.access_scope = 'admin'
                """
            ).fetchone()
        return int(row["count"])

    @staticmethod
    def count_users() -> int:
        with connection_scope() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"])

    @staticmethod
    def ensure_admin(username: str, password: str) -> bool:
        """确保唯一超管存在；兼容旧 admin，但永不重置已有密码。"""
        admin_role = RoleRepository.get_by_code("admin")
        if not admin_role:
            return False
        try:
            with connection_scope() as connection:
                existing_super = connection.execute(
                    "SELECT id FROM users WHERE is_superadmin = 1 LIMIT 1"
                ).fetchone()
                if existing_super:
                    return False
                existing = connection.execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ).fetchone()
                if existing:
                    connection.execute(
                        """
                        UPDATE users
                        SET role = 'admin', role_id = ?, status = 'enabled',
                            is_superadmin = 1, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (admin_role["id"], existing["id"]),
                    )
                    connection.commit()
                    return False

                salt = secrets.token_bytes(16)
                connection.execute(
                    """
                    INSERT INTO users
                        (username, password_hash, salt, role, role_id, is_superadmin)
                    VALUES (?, ?, ?, 'admin', ?, 1)
                    """,
                    (username, _hash_password(password, salt), salt.hex(), admin_role["id"]),
                )
                connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False
