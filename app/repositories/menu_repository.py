"""菜单 SQL、持久化和角色菜单转换。"""

from __future__ import annotations

import sqlite3

from app.models.db import connection_scope

MENU_GROUP_META = {
    "控制台": {"code": "01"},
    "权限与系统": {"code": "02"},
    "瞭望与数据": {"code": "03"},
    "模型与问数": {"code": "04"},
    "数智监管": {"code": "05"},
    "安全审计": {"code": "06"},
}


def _dict(row):
    return dict(row) if row is not None else None


class MenuRepository:
    @staticmethod
    def list_menus(keyword: str = "") -> list[dict]:
        pattern = f"%{keyword}%"
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT m.*, f.code AS feature_code, f.name AS feature_name,
                       f.route,
                       CASE WHEN f.enabled=1 AND (f.parent_id IS NULL OR p.enabled=1)
                            THEN 1 ELSE 0 END AS feature_enabled,
                       f.parent_id, p.name AS parent_name,
                       COUNT(DISTINCT rf.role_id) AS role_count
                FROM menus m
                JOIN features f ON f.id=m.feature_id
                LEFT JOIN features p ON p.id=f.parent_id
                LEFT JOIN role_features rf ON rf.feature_id=f.id
                WHERE (?='' OR m.title LIKE ? OR f.name LIKE ? OR f.code LIKE ?)
                GROUP BY m.id ORDER BY m.sort_order,m.id
                """,
                (keyword, pattern, pattern, pattern),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def get(menu_id: int):
        with connection_scope() as connection:
            return _dict(connection.execute("SELECT * FROM menus WHERE id=?", (menu_id,)).fetchone())

    @staticmethod
    def create(feature_id: int, title: str, icon: str, category: str, sort_order: int) -> bool:
        try:
            with connection_scope() as connection:
                connection.execute(
                    "INSERT INTO menus(feature_id,title,icon,category,sort_order) VALUES (?,?,?,?,?)",
                    (feature_id, title, icon, category, sort_order),
                )
                connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    @staticmethod
    def update(menu_id: int, title: str, icon: str, category: str, sort_order: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                """UPDATE menus SET title=?,icon=?,category=?,sort_order=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=?""",
                (title, icon, category, sort_order, menu_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def set_enabled(menu_id: int, enabled: bool) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                "UPDATE menus SET enabled=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (int(enabled), menu_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def delete(menu_id: int) -> tuple[bool, str]:
        with connection_scope() as connection:
            row = connection.execute("SELECT is_system FROM menus WHERE id=?", (menu_id,)).fetchone()
            if row is None:
                return False, "菜单不存在"
            if row["is_system"]:
                return False, "内置菜单不能删除，可以将其隐藏"
            connection.execute("DELETE FROM menus WHERE id=?", (menu_id,))
            connection.commit()
        return True, "菜单已删除"

    @staticmethod
    def move(menu_id: int, direction: str) -> bool:
        with connection_scope() as connection:
            current = connection.execute("SELECT id,sort_order FROM menus WHERE id=?", (menu_id,)).fetchone()
            if current is None:
                return False
            operator, order = ("<", "DESC") if direction == "up" else (">", "ASC")
            neighbor = connection.execute(
                f"SELECT id,sort_order FROM menus WHERE sort_order {operator} ? ORDER BY sort_order {order},id {order} LIMIT 1",
                (current["sort_order"],),
            ).fetchone()
            if neighbor is None:
                return False
            connection.execute("UPDATE menus SET sort_order=? WHERE id=?", (neighbor["sort_order"], current["id"]))
            connection.execute("UPDATE menus SET sort_order=? WHERE id=?", (current["sort_order"], neighbor["id"]))
            connection.commit()
        return True

    @staticmethod
    def list_for_role(role_id: int) -> list[dict]:
        with connection_scope() as connection:
            rows = connection.execute(
                """SELECT m.id,m.title,m.icon,m.category,m.sort_order,
                       f.id AS feature_id,f.code,f.route
                FROM menus m
                JOIN features f ON f.id=m.feature_id AND f.enabled=1
                LEFT JOIN features p ON p.id=f.parent_id
                JOIN role_features rf ON rf.feature_id=f.id AND rf.role_id=?
                JOIN roles r ON r.id=rf.role_id AND r.enabled=1
                WHERE m.enabled=1 AND (f.parent_id IS NULL OR p.enabled=1)
                ORDER BY m.sort_order,m.id""",
                (role_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def grouped_for_role(role_id: int) -> list[dict]:
        """按任务域稳定分组，同名类别只出现一次。"""
        groups: dict[str, dict] = {}
        for item in MenuRepository.list_for_role(role_id):
            category = item["category"]
            if category not in groups:
                meta = MENU_GROUP_META.get(category, {"code": "--"})
                groups[category] = {
                    "category": category,
                    "code": meta["code"],
                    "items": [],
                }
            groups[category]["items"].append(item)
        return list(groups.values())
