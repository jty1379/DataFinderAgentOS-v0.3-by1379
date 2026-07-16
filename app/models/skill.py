"""技能配置 Repository。"""

from __future__ import annotations

import json
import re
import sqlite3

from app.models.db import connection_scope

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,39}$")


def _bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _json_object(value, field_name: str) -> dict:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name}必须是 JSON 对象") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name}必须是 JSON 对象")
    return parsed


def _decode(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    for name in ("tools", "triggers"):
        try:
            item[name] = json.loads(item.get(name) or "[]")
        except json.JSONDecodeError:
            item[name] = []
    for name in ("enabled",):
        item[name] = bool(item.get(name))
    return item


class SkillRepository:
    @staticmethod
    def list(
        keyword: str = "",
        status: str = "",
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[dict], int]:
        page = max(1, int(page or 1))
        page_size = min(50, max(1, int(page_size or 10)))
        keyword = keyword.strip()
        pattern = f"%{keyword}%"
        clauses = ["(? = '' OR code LIKE ? OR name LIKE ? OR description LIKE ?)"]
        params: list[object] = [keyword, pattern, pattern, pattern]
        normalized_status = status.strip().lower()
        if normalized_status in {"1", "enabled", "true"}:
            clauses.append("enabled = 1")
        elif normalized_status in {"0", "disabled", "false"}:
            clauses.append("enabled = 0")
        where = " AND ".join(clauses)
        with connection_scope() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM skills WHERE " + where, params
                ).fetchone()["count"]
            )
            rows = connection.execute(
                """
                SELECT s.*,
                       COUNT(es.employee_id) AS employee_count
                FROM skills s
                LEFT JOIN employee_skills es ON es.skill_id = s.id
                WHERE """ + where +
                " GROUP BY s.id ORDER BY s.id DESC LIMIT ? OFFSET ?",
                (*params, page_size, (page - 1) * page_size),
            ).fetchall()
        return [_decode(row) for row in rows], total

    @staticmethod
    def get(skill_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT s.*,
                       COUNT(es.employee_id) AS employee_count
                FROM skills s
                LEFT JOIN employee_skills es ON es.skill_id = s.id
                WHERE s.id = ?
                GROUP BY s.id
                """,
                (skill_id,),
            ).fetchone()
        return _decode(row)

    @staticmethod
    def get_by_code(code: str):
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT * FROM skills WHERE code = ?", (code,)
            ).fetchone()
        return _decode(row)

    @staticmethod
    def all_enabled() -> list[dict]:
        with connection_scope() as connection:
            rows = connection.execute(
                "SELECT * FROM skills WHERE enabled = 1 ORDER BY id ASC"
            ).fetchall()
        return [_decode(row) for row in rows]

    @staticmethod
    def _normalized(values: dict, current: dict | None = None) -> dict:
        current = current or {}
        code = str(values.get("code", current.get("code", ""))).strip().lower()
        name = str(values.get("name", current.get("name", ""))).strip()
        if not CODE_PATTERN.fullmatch(code):
            raise ValueError("编码需以小写字母开头，仅含小写字母、数字和下划线，长度 3—40")
        if not 2 <= len(name) <= 60:
            raise ValueError("技能名称需为 2—60 个字符")
        description = str(values.get("description", current.get("description", ""))).strip()[:500]
        system_prompt = str(values.get("system_prompt", current.get("system_prompt", ""))).strip()[:10000]
        trigger_condition = str(values.get("trigger_condition", current.get("trigger_condition", ""))).strip()
        tools = _json_object(values.get("tools", current.get("tools", {})), "工具配置")
        triggers = _json_object(values.get("triggers", current.get("triggers", {})), "触发配置")
        return {
            "code": code,
            "name": name,
            "description": description,
            "system_prompt": system_prompt,
            "trigger_condition": trigger_condition,
            "tools": json.dumps(tools, ensure_ascii=False),
            "triggers": json.dumps(triggers, ensure_ascii=False),
            "enabled": int(_bool(values.get("enabled", current.get("enabled", True)))),
        }

    @staticmethod
    def create(**values) -> int | None:
        data = SkillRepository._normalized(values)
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO skills
                        (code, name, description, system_prompt, trigger_condition,
                         tools, triggers, enabled, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["code"],
                        data["name"],
                        data["description"],
                        data["system_prompt"],
                        data["trigger_condition"],
                        data["tools"],
                        data["triggers"],
                        data["enabled"],
                        values.get("created_by"),
                    ),
                )
                connection.commit()
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None

    @staticmethod
    def update(skill_id: int, **values) -> bool:
        current = SkillRepository.get(skill_id)
        if not current:
            return False
        data = SkillRepository._normalized(values, current)
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    UPDATE skills SET
                        code = ?, name = ?, description = ?, system_prompt = ?,
                        trigger_condition = ?, tools = ?, triggers = ?,
                        enabled = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        data["code"],
                        data["name"],
                        data["description"],
                        data["system_prompt"],
                        data["trigger_condition"],
                        data["tools"],
                        data["triggers"],
                        data["enabled"],
                        skill_id,
                    ),
                )
                connection.commit()
            return cursor.rowcount == 1
        except sqlite3.IntegrityError:
            return False

    @staticmethod
    def delete(skill_id: int) -> bool:
        with connection_scope() as connection:
            connection.execute("DELETE FROM employee_skills WHERE skill_id = ?", (skill_id,))
            cursor = connection.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def toggle(skill_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                UPDATE skills SET
                    enabled = CASE enabled WHEN 1 THEN 0 ELSE 1 END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (skill_id,),
            )
            connection.commit()
        return cursor.rowcount == 1


class EmployeeSkillRepository:
    @staticmethod
    def list_by_employee(employee_id: int) -> list[dict]:
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT s.*, es.created_at AS bound_at
                FROM employee_skills es
                JOIN skills s ON s.id = es.skill_id
                WHERE es.employee_id = ?
                ORDER BY es.created_at DESC
                """,
                (employee_id,),
            ).fetchall()
        return [_decode(row) for row in rows]

    @staticmethod
    def list_by_skill(skill_id: int) -> list[dict]:
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT d.id, d.name, d.code, d.mention, d.employee_type,
                       es.created_at AS bound_at
                FROM employee_skills es
                JOIN digital_employees d ON d.id = es.employee_id
                WHERE es.skill_id = ?
                ORDER BY es.created_at DESC
                """,
                (skill_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def bind(employee_id: int, skill_id: int) -> bool:
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO employee_skills
                        (employee_id, skill_id)
                    VALUES (?, ?)
                    """,
                    (employee_id, skill_id),
                )
                connection.commit()
            return cursor.rowcount == 1
        except sqlite3.IntegrityError:
            return False

    @staticmethod
    def unbind(employee_id: int, skill_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                "DELETE FROM employee_skills WHERE employee_id = ? AND skill_id = ?",
                (employee_id, skill_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def unbind_all(employee_id: int) -> None:
        with connection_scope() as connection:
            connection.execute("DELETE FROM employee_skills WHERE employee_id = ?", (employee_id,))
            connection.commit()