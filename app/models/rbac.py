"""角色、功能、菜单与授权关系的 Repository。"""

from __future__ import annotations

import math
import sqlite3

from app.models.db import connection_scope


def _dict(row):
    return dict(row) if row is not None else None


def _pagination(page: int, page_size: int, total: int) -> dict:
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


class RoleRepository:
    @staticmethod
    def list_roles(keyword: str = "") -> list[dict]:
        pattern = f"%{keyword}%"
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT r.*,
                       COUNT(DISTINCT u.id) AS user_count,
                       COUNT(DISTINCT rf.feature_id) AS feature_count
                FROM roles r
                LEFT JOIN users u ON u.role_id = r.id
                LEFT JOIN role_features rf ON rf.role_id = r.id
                WHERE (? = '' OR r.name LIKE ? OR r.code LIKE ?)
                GROUP BY r.id
                ORDER BY r.is_system DESC, r.id
                """,
                (keyword, pattern, pattern),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def paginate_roles(
        keyword: str = "", page: int = 1, page_size: int = 20
    ) -> tuple[list[dict], dict]:
        pattern = f"%{keyword}%"
        with connection_scope() as connection:
            total_row = connection.execute(
                """
                SELECT COUNT(*) AS total FROM roles r
                WHERE (? = '' OR r.name LIKE ? OR r.code LIKE ?)
                """,
                (keyword, pattern, pattern),
            ).fetchone()
            pagination = _pagination(page, page_size, int(total_row["total"]))
            rows = connection.execute(
                """
                SELECT r.*,
                       COUNT(DISTINCT u.id) AS user_count,
                       COUNT(DISTINCT rf.feature_id) AS feature_count
                FROM roles r
                LEFT JOIN users u ON u.role_id = r.id
                LEFT JOIN role_features rf ON rf.role_id = r.id
                WHERE (? = '' OR r.name LIKE ? OR r.code LIKE ?)
                GROUP BY r.id
                ORDER BY r.is_system DESC, r.id
                LIMIT ? OFFSET ?
                """,
                (
                    keyword,
                    pattern,
                    pattern,
                    pagination["page_size"],
                    (pagination["page"] - 1) * pagination["page_size"],
                ),
            ).fetchall()
        return [dict(row) for row in rows], pagination

    @staticmethod
    def get(role_id: int):
        with connection_scope() as connection:
            return _dict(connection.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone())

    @staticmethod
    def get_by_code(code: str):
        with connection_scope() as connection:
            return _dict(connection.execute("SELECT * FROM roles WHERE code = ?", (code,)).fetchone())

    @staticmethod
    def create(code: str, name: str, description: str, access_scope: str) -> bool:
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO roles (code, name, description, access_scope)
                    VALUES (?, ?, ?, ?)
                    """,
                    (code, name, description, access_scope),
                )
                if access_scope == "user":
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO role_features (role_id, feature_id)
                        SELECT ?, id FROM features WHERE code = 'user_portal'
                        """,
                        (cursor.lastrowid,),
                    )
                connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    @staticmethod
    def update(role_id: int, name: str, description: str, access_scope: str, enabled: bool) -> bool:
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT code, is_system FROM roles WHERE id = ?", (role_id,)
            ).fetchone()
            if row is None:
                return False
            # 默认系统管理员角色是权限根基，名称、范围、状态与权限均不可改。
            if row["code"] == "admin":
                return False
            if row["is_system"]:
                cursor = connection.execute(
                    """
                    UPDATE roles SET name = ?, description = ?, enabled = ?,
                                     updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (name, description, int(enabled), role_id),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE roles SET name = ?, description = ?, access_scope = ?, enabled = ?,
                                     updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (name, description, access_scope, int(enabled), role_id),
                )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def delete(role_id: int) -> tuple[bool, str]:
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT is_system, (SELECT COUNT(*) FROM users WHERE role_id = roles.id) AS user_count
                FROM roles WHERE id = ?
                """,
                (role_id,),
            ).fetchone()
            if row is None:
                return False, "角色不存在"
            if row["is_system"]:
                return False, "系统默认角色不能删除"
            if row["user_count"]:
                return False, "该角色仍有关联用户，不能删除"
            connection.execute("DELETE FROM roles WHERE id = ?", (role_id,))
            connection.commit()
        return True, "角色已删除"

    @staticmethod
    def feature_ids(role_id: int) -> set[int]:
        with connection_scope() as connection:
            rows = connection.execute(
                "SELECT feature_id FROM role_features WHERE role_id = ?", (role_id,)
            ).fetchall()
        return {int(row["feature_id"]) for row in rows}

    @staticmethod
    def set_features(role_id: int, feature_ids: list[int]) -> bool:
        with connection_scope() as connection:
            role = connection.execute(
                "SELECT code FROM roles WHERE id = ?", (role_id,)
            ).fetchone()
            if role is None:
                return False
            if role["code"] == "admin":
                return False
            valid_ids = {
                int(row["id"])
                for row in connection.execute(
                    """
                    SELECT f.id
                    FROM features f
                    LEFT JOIN features p ON p.id = f.parent_id
                    WHERE f.enabled = 1
                      AND (f.parent_id IS NULL OR p.enabled = 1)
                    """
                ).fetchall()
            }
            selected_ids = sorted(set(feature_ids) & valid_ids)
            connection.execute("DELETE FROM role_features WHERE role_id = ?", (role_id,))
            connection.executemany(
                "INSERT OR IGNORE INTO role_features (role_id, feature_id) VALUES (?, ?)",
                ((role_id, feature_id) for feature_id in selected_ids),
            )
            connection.commit()
        return True

    @staticmethod
    def has_feature(role_id: int, feature_code: str) -> bool:
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM role_features rf
                JOIN roles r ON r.id = rf.role_id AND r.enabled = 1
                JOIN features f ON f.id = rf.feature_id AND f.enabled = 1
                LEFT JOIN features p ON p.id = f.parent_id
                WHERE rf.role_id = ? AND f.code = ?
                      AND (f.parent_id IS NULL OR p.enabled = 1)
                """,
                (role_id, feature_code),
            ).fetchone()
        return row is not None


class FeatureRepository:
    @staticmethod
    def list_features(keyword: str = "", enabled: str = "") -> list[dict]:
        pattern = f"%{keyword}%"
        params: list[object] = [keyword, pattern, pattern, pattern, pattern]
        status_sql = ""
        if enabled in {"0", "1"}:
            status_sql = " AND f.enabled = ?"
            params.append(int(enabled))
        with connection_scope() as connection:
            rows = connection.execute(
                f"""
                SELECT f.*, p.name AS parent_name,
                       CASE WHEN f.parent_id IS NULL THEN 1 ELSE 2 END AS level,
                       COUNT(DISTINCT rf.role_id) AS role_count,
                       CASE WHEN m.id IS NULL THEN 0 ELSE 1 END AS has_menu
                FROM features f
                LEFT JOIN features p ON p.id = f.parent_id
                LEFT JOIN role_features rf ON rf.feature_id = f.id
                LEFT JOIN menus m ON m.feature_id = f.id
                WHERE (? = '' OR f.name LIKE ? OR f.code LIKE ? OR f.route LIKE ?
                                  OR p.name LIKE ?)
                {status_sql}
                GROUP BY f.id
                ORDER BY COALESCE(p.sort_order, f.sort_order),
                         CASE WHEN f.parent_id IS NULL THEN 0 ELSE 1 END,
                         f.sort_order, f.id
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def paginate_features(
        keyword: str = "",
        enabled: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], dict]:
        pattern = f"%{keyword}%"
        params: list[object] = [keyword, pattern, pattern, pattern, pattern]
        status_sql = ""
        if enabled in {"0", "1"}:
            status_sql = " AND f.enabled = ?"
            params.append(int(enabled))
        with connection_scope() as connection:
            total_row = connection.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM features f
                LEFT JOIN features p ON p.id = f.parent_id
                WHERE (? = '' OR f.name LIKE ? OR f.code LIKE ? OR f.route LIKE ?
                                  OR p.name LIKE ?)
                {status_sql}
                """,
                params,
            ).fetchone()
            pagination = _pagination(page, page_size, int(total_row["total"]))
            rows = connection.execute(
                f"""
                SELECT f.*, p.name AS parent_name,
                       CASE WHEN f.parent_id IS NULL THEN 1 ELSE 2 END AS level,
                       COUNT(DISTINCT rf.role_id) AS role_count,
                       CASE WHEN m.id IS NULL THEN 0 ELSE 1 END AS has_menu
                FROM features f
                LEFT JOIN features p ON p.id = f.parent_id
                LEFT JOIN role_features rf ON rf.feature_id = f.id
                LEFT JOIN menus m ON m.feature_id = f.id
                WHERE (? = '' OR f.name LIKE ? OR f.code LIKE ? OR f.route LIKE ?
                                  OR p.name LIKE ?)
                {status_sql}
                GROUP BY f.id
                ORDER BY COALESCE(p.sort_order, f.sort_order),
                         CASE WHEN f.parent_id IS NULL THEN 0 ELSE 1 END,
                         f.sort_order, f.id
                LIMIT ? OFFSET ?
                """,
                [
                    *params,
                    pagination["page_size"],
                    (pagination["page"] - 1) * pagination["page_size"],
                ],
            ).fetchall()
        return [dict(row) for row in rows], pagination

    @staticmethod
    def tree_features() -> list[dict]:
        """Return roots and their children for the Layui role-permission tree."""
        items = FeatureRepository.list_features()
        nodes = {item["id"]: {**item, "children": []} for item in items}
        roots: list[dict] = []
        for item in items:
            node = nodes[item["id"]]
            parent = nodes.get(item["parent_id"])
            if parent is None:
                roots.append(node)
            else:
                parent["children"].append(node)
        return roots

    @staticmethod
    def get(feature_id: int):
        with connection_scope() as connection:
            return _dict(
                connection.execute(
                    """
                    SELECT f.*, p.name AS parent_name,
                           CASE WHEN f.parent_id IS NULL THEN 1 ELSE 2 END AS level
                    FROM features f
                    LEFT JOIN features p ON p.id = f.parent_id
                    WHERE f.id = ?
                    """,
                    (feature_id,),
                ).fetchone()
            )

    @staticmethod
    def _valid_parent(connection, feature_id: int | None, parent_id: int | None) -> bool:
        if parent_id in {None, 0}:
            return True
        if feature_id is not None and parent_id == feature_id:
            return False
        parent = connection.execute(
            "SELECT id, parent_id FROM features WHERE id = ?", (parent_id,)
        ).fetchone()
        # Only a root feature can be selected as parent, so depth never exceeds two.
        if parent is None or parent["parent_id"] is not None:
            return False
        if feature_id is not None:
            child = connection.execute(
                "SELECT 1 FROM features WHERE parent_id = ? LIMIT 1", (feature_id,)
            ).fetchone()
            if child is not None:
                return False
        return True

    @staticmethod
    def create(
        code: str,
        name: str,
        route: str,
        icon: str,
        category: str,
        description: str,
        sort_order: int,
        parent_id: int | None = None,
    ) -> bool:
        try:
            with connection_scope() as connection:
                normalized_parent = int(parent_id) if parent_id else None
                if not FeatureRepository._valid_parent(connection, None, normalized_parent):
                    return False
                connection.execute(
                    """
                    INSERT INTO features
                        (parent_id, code, name, route, icon, category, description, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_parent,
                        code,
                        name,
                        route,
                        icon,
                        category,
                        description,
                        sort_order,
                    ),
                )
                connection.commit()
            return True
        except (sqlite3.IntegrityError, TypeError, ValueError):
            return False

    @staticmethod
    def update(
        feature_id: int,
        name: str,
        route: str,
        icon: str,
        category: str,
        description: str,
        sort_order: int,
        parent_id: int | None = None,
    ) -> bool:
        try:
            with connection_scope() as connection:
                normalized_parent = int(parent_id) if parent_id else None
                existing = connection.execute(
                    "SELECT id FROM features WHERE id = ?", (feature_id,)
                ).fetchone()
                if existing is None or not FeatureRepository._valid_parent(
                    connection, feature_id, normalized_parent
                ):
                    return False
                cursor = connection.execute(
                    """
                    UPDATE features SET parent_id = ?, name = ?, route = ?, icon = ?, category = ?,
                                        description = ?, sort_order = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        normalized_parent,
                        name,
                        route,
                        icon,
                        category,
                        description,
                        sort_order,
                        feature_id,
                    ),
                )
                connection.commit()
            return cursor.rowcount == 1
        except (sqlite3.IntegrityError, TypeError, ValueError):
            return False

    @staticmethod
    def set_enabled(feature_id: int, enabled: bool) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                "UPDATE features SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(enabled), feature_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def delete(feature_id: int) -> tuple[bool, str]:
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT f.is_system,
                       (SELECT COUNT(*) FROM features WHERE parent_id = f.id) AS child_count
                FROM features f WHERE f.id = ?
                """,
                (feature_id,),
            ).fetchone()
            if row is None:
                return False, "功能不存在"
            if row["is_system"]:
                return False, "内置功能不能删除，可以将其禁用"
            if row["child_count"]:
                return False, "一级功能仍有二级功能，请先删除或移动子功能"
            connection.execute("DELETE FROM features WHERE id = ?", (feature_id,))
            connection.commit()
        return True, "功能已删除"


# 兼容旧导入路径；新代码应使用 app.repositories.menu_repository。
from app.repositories.menu_repository import MenuRepository as MenuRepository  # noqa: E402,F401
