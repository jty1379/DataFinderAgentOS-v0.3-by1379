"""数字员工配置 Repository。"""

from __future__ import annotations

import json
import re
import sqlite3
from urllib.parse import urlsplit

from app.models.db import connection_scope

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
EMPLOYEE_TYPES = {"llm", "api"}


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


def _skills(value) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        items = value
    else:
        text = str(value).strip()
        if text.startswith("["):
            try:
                items = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError("技能列表格式不正确") from exc
        else:
            items = re.split(r"[,，\n]", text)
    result: list[str] = []
    for item in items:
        label = str(item).strip()
        if label and label not in result:
            result.append(label[:40])
    return result[:20]


def _employee(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    for name, fallback in (
        ("skills", []),
        ("crawl4ai_config", {}),
        ("request_headers", {}),
        ("request_params", {}),
    ):
        try:
            item[name] = json.loads(item.get(name) or json.dumps(fallback))
        except json.JSONDecodeError:
            item[name] = fallback
    for name in ("use_default_model", "crawl4ai_enabled", "enabled", "is_system"):
        item[name] = bool(item.get(name))
    return item


class DigitalEmployeeRepository:
    @staticmethod
    def list(
        keyword: str = "",
        employee_type: str = "",
        status: str = "",
        page: int = 1,
        page_size: int = 8,
    ) -> tuple[list[dict], int]:
        page = max(1, int(page or 1))
        page_size = min(50, max(1, int(page_size or 8)))
        keyword = keyword.strip()
        pattern = f"%{keyword}%"
        clauses = ["(? = '' OR d.name LIKE ? OR d.mention LIKE ? OR d.description LIKE ?)"]
        params: list[object] = [keyword, pattern, pattern, pattern]
        if employee_type in EMPLOYEE_TYPES:
            clauses.append("d.employee_type = ?")
            params.append(employee_type)
        if status in {"enabled", "1", "true"}:
            clauses.append("d.enabled = 1")
        elif status in {"disabled", "0", "false"}:
            clauses.append("d.enabled = 0")
        where = " AND ".join(clauses)
        with connection_scope() as connection:
            total = int(connection.execute(
                "SELECT COUNT(*) AS count FROM digital_employees d WHERE " + where,
                params,
            ).fetchone()["count"])
            rows = connection.execute(
                """
                SELECT d.*, m.name AS model_name_display, m.model_name AS model_call_name,
                       i.name AS interface_name, i.enabled AS interface_enabled
                FROM digital_employees d
                LEFT JOIN model_configs m ON m.id = d.model_id
                LEFT JOIN api_interfaces i ON i.id = d.interface_id
                WHERE """ + where +
                " ORDER BY d.is_system DESC, d.id DESC LIMIT ? OFFSET ?",
                (*params, page_size, (page - 1) * page_size),
            ).fetchall()
        return [_employee(row) for row in rows], total

    @staticmethod
    def get(employee_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT d.*, m.name AS model_name_display, m.model_name AS model_call_name,
                       i.name AS interface_name, i.enabled AS interface_enabled
                FROM digital_employees d
                LEFT JOIN model_configs m ON m.id = d.model_id
                LEFT JOIN api_interfaces i ON i.id = d.interface_id
                WHERE d.id = ?
                """,
                (employee_id,),
            ).fetchone()
        return _employee(row)

    @staticmethod
    def get_by_code(code: str):
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT * FROM digital_employees WHERE code = ?", (code,)
            ).fetchone()
        return _employee(row)

    @staticmethod
    def _normalized(values: dict, current: dict | None = None) -> dict:
        current = current or {}
        employee_type = str(values.get("employee_type", current.get("employee_type", "llm"))).strip()
        if employee_type not in EMPLOYEE_TYPES:
            raise ValueError("数字员工类型无效")
        code = str(values.get("code", current.get("code", ""))).strip().lower()
        name = str(values.get("name", current.get("name", ""))).strip()
        mention = str(values.get("mention", current.get("mention", name))).strip().lstrip("@").strip()
        description = str(values.get("description", current.get("description", ""))).strip()
        if not CODE_PATTERN.fullmatch(code):
            raise ValueError("编码需以小写字母开头，仅含小写字母、数字和下划线，长度 3—40")
        if not 2 <= len(name) <= 40 or not 2 <= len(mention) <= 30:
            raise ValueError("名称或 @调度名长度不正确")
        if any(char.isspace() for char in mention):
            raise ValueError("@调度名不能包含空格")
        model_id = values.get("model_id", current.get("model_id"))
        try:
            model_id = int(model_id) if model_id not in (None, "", 0, "0") else None
        except (TypeError, ValueError) as exc:
            raise ValueError("指定模型编号不正确") from exc
        interface_id = values.get("interface_id", current.get("interface_id"))
        try:
            interface_id = (
                int(interface_id) if interface_id not in (None, "", 0, "0") else None
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("绑定接口编号不正确") from exc
        use_default_model = _bool(values.get("use_default_model", current.get("use_default_model", True)))
        system_prompt = str(values.get("system_prompt", current.get("system_prompt", ""))).strip()
        prompt_template = str(values.get("prompt_template", current.get("prompt_template", "{{input}}"))).strip()
        skills = _skills(values.get("skills", current.get("skills", [])))
        crawl_enabled = _bool(values.get("crawl4ai_enabled", current.get("crawl4ai_enabled", False)))
        crawl_config = _json_object(values.get("crawl4ai_config", current.get("crawl4ai_config", {})), "采集配置")
        api_method = str(values.get("api_method", current.get("api_method", "GET"))).upper().strip()
        api_url = str(values.get("api_url", current.get("api_url", ""))).strip()
        request_headers = _json_object(values.get("request_headers", current.get("request_headers", {})), "请求头")
        request_params = _json_object(values.get("request_params", current.get("request_params", {})), "请求参数")
        response_mode = str(values.get("response_mode", current.get("response_mode", "json"))).strip()
        timeout_seconds = int(values.get("timeout_seconds", current.get("timeout_seconds", 20)) or 20)
        if employee_type == "llm":
            if not system_prompt:
                raise ValueError("模型型数字员工必须填写系统提示词")
            if "{{input}}" not in prompt_template:
                raise ValueError("提示词模板必须包含 {{input}}")
            api_url = ""
            request_headers = {}
            request_params = {}
            interface_id = None
        else:
            if not interface_id:
                parsed = urlsplit(api_url)
                if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                    raise ValueError("接口型数字员工必须绑定托管接口或填写完整的 http/https 地址")
                if parsed.username or parsed.password:
                    raise ValueError("接口地址不允许嵌入凭据")
            if api_method not in {"GET", "POST"} or response_mode not in {"json", "card"}:
                raise ValueError("接口方法或响应模式无效")
            if any(str(key).lower() in {"cookie", "authorization", "proxy-authorization"} for key in request_headers):
                raise ValueError("请求头中禁止保存 Cookie 或鉴权凭据")
            model_id = None
            use_default_model = False
            system_prompt = ""
            prompt_template = "{{input}}"
            crawl_enabled = False
            crawl_config = {}
        if not 3 <= timeout_seconds <= 60:
            raise ValueError("超时时间需为 3—60 秒")
        return {
            "code": code, "name": name, "mention": mention,
            "employee_type": employee_type, "description": description[:500],
            "model_id": model_id, "interface_id": interface_id,
            "use_default_model": int(use_default_model),
            "system_prompt": system_prompt[:10000], "prompt_template": prompt_template[:10000],
            "skills": json.dumps(skills, ensure_ascii=False),
            "crawl4ai_enabled": int(crawl_enabled),
            "crawl4ai_config": json.dumps(crawl_config, ensure_ascii=False),
            "api_method": api_method, "api_url": api_url,
            "request_headers": json.dumps(request_headers, ensure_ascii=False),
            "request_params": json.dumps(request_params, ensure_ascii=False),
            "response_mode": response_mode, "timeout_seconds": timeout_seconds,
            "enabled": int(_bool(values.get("enabled", current.get("enabled", True)))),
            "created_by": values.get("created_by", current.get("created_by")),
        }

    @staticmethod
    def create(**values) -> int | None:
        data = DigitalEmployeeRepository._normalized(values)
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO digital_employees
                        (code, name, mention, employee_type, description, model_id, interface_id,
                         use_default_model, system_prompt, prompt_template, skills,
                         crawl4ai_enabled, crawl4ai_config, api_method, api_url,
                         request_headers, request_params, response_mode, timeout_seconds,
                         enabled, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    tuple(data[key] for key in data),
                )
                connection.commit()
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None

    @staticmethod
    def update(employee_id: int, **values) -> bool:
        current = DigitalEmployeeRepository.get(employee_id)
        if not current:
            return False
        if current["is_system"]:
            values["code"] = current["code"]
            values["name"] = current["name"]
            values["mention"] = current["mention"]
            values["employee_type"] = current["employee_type"]
            values["enabled"] = True
        data = DigitalEmployeeRepository._normalized(values, current)
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    UPDATE digital_employees SET
                        code=?, name=?, mention=?, employee_type=?, description=?, model_id=?, interface_id=?,
                        use_default_model=?, system_prompt=?, prompt_template=?, skills=?,
                        crawl4ai_enabled=?, crawl4ai_config=?, api_method=?, api_url=?,
                        request_headers=?, request_params=?, response_mode=?, timeout_seconds=?,
                        enabled=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (*tuple(data[key] for key in data if key != "created_by"), employee_id),
                )
                connection.commit()
            return cursor.rowcount == 1
        except sqlite3.IntegrityError:
            return False

    @staticmethod
    def delete(employee_id: int) -> tuple[bool, str]:
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT is_system FROM digital_employees WHERE id = ?", (employee_id,)
            ).fetchone()
            if row is None:
                return False, "数字员工不存在"
            if row["is_system"]:
                return False, "系统采集专员不可删除"
            cursor = connection.execute("DELETE FROM digital_employees WHERE id = ?", (employee_id,))
            connection.commit()
        return cursor.rowcount == 1, "数字员工已删除"

    @staticmethod
    def toggle(employee_id: int) -> tuple[bool, str]:
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT enabled, is_system FROM digital_employees WHERE id = ?", (employee_id,)
            ).fetchone()
            if row is None:
                return False, "数字员工不存在"
            if row["is_system"]:
                return False, "系统采集专员必须保持启用"
            connection.execute(
                "UPDATE digital_employees SET enabled = CASE enabled WHEN 1 THEN 0 ELSE 1 END, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (employee_id,),
            )
            connection.commit()
        return True, "状态已更新"

    @staticmethod
    def record_call(employee_id: int, success: bool) -> None:
        """记录数字员工的调用次数和失败次数。"""
        with connection_scope() as connection:
            if success:
                connection.execute(
                    "UPDATE digital_employees SET call_count = COALESCE(call_count, 0) + 1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (employee_id,),
                )
            else:
                connection.execute(
                    "UPDATE digital_employees SET call_count = COALESCE(call_count, 0) + 1, failure_count = COALESCE(failure_count, 0) + 1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (employee_id,),
                )
            connection.commit()

    @staticmethod
    def record_call_log(
        employee_id: int,
        user_id: int | None,
        input_text: str,
        success: bool,
        response_data: str | None = None,
        error_message: str | None = None,
        latency_ms: int = 0,
        tokens_used: int = 0,
    ) -> None:
        """记录数字员工的详细调用日志。"""
        with connection_scope() as connection:
            connection.execute(
                """INSERT INTO employee_call_logs
                (employee_id, user_id, input_text, success, response_data, error_message, latency_ms, tokens_used)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (employee_id, user_id, input_text[:2000], int(success), response_data, error_message, latency_ms, tokens_used),
            )
            connection.commit()

    @staticmethod
    def list_call_logs(employee_id: int, limit: int = 20) -> list[dict]:
        """获取数字员工的最近调用日志。"""
        with connection_scope() as connection:
            rows = connection.execute(
                """SELECT * FROM employee_call_logs
                WHERE employee_id = ?
                ORDER BY created_at DESC
                LIMIT ?""",
                (employee_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]
