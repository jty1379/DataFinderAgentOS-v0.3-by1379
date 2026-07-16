"""接口配置与调用日志 Repository。"""

from __future__ import annotations

import json
import re
import sqlite3
from urllib.parse import urlsplit

from app.models.db import connection_scope

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
REQUEST_METHODS = {"GET", "POST"}
FORBIDDEN_HEADERS = {"authorization", "cookie", "host", "connection", "proxy-authorization"}


def _bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _json_object(value, label: str) -> str:
    if value in (None, ""):
        parsed = {}
    elif isinstance(value, dict):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label}必须是 JSON 对象") from exc
    else:
        raise ValueError(f"{label}必须是 JSON 对象")
    if not isinstance(parsed, dict):
        raise ValueError(f"{label}必须是 JSON 对象")
    normalized = {str(key): str(value) for key, value in parsed.items()}
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def _headers_json(value) -> str:
    if value in (None, ""):
        parsed = {}
    elif isinstance(value, dict):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("请求头必须是 JSON 对象") from exc
    else:
        raise ValueError("请求头必须是 JSON 对象")
    if not isinstance(parsed, dict):
        raise ValueError("请求头必须是 JSON 对象")
    normalized: dict[str, str] = {}
    for key, raw_value in parsed.items():
        name = str(key).strip().lower()
        if name in FORBIDDEN_HEADERS:
            raise ValueError("请求头不允许包含：authorization、cookie、host、connection、proxy-authorization")
        if not key.strip() or "\n" in key or "\r" in key:
            raise ValueError("请求头名称不正确")
        text = str(raw_value).strip()
        if "\n" in text or "\r" in text:
            raise ValueError("请求头值不允许包含换行符")
        normalized[str(key).strip()] = text[:1000]
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def _valid_http_url(value: str) -> str:
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("接口地址仅支持完整的 http/https URL")
    if parsed.username or parsed.password:
        raise ValueError("接口地址不允许嵌入凭据")
    return value


def _decode(row, json_fields: tuple[str, ...]) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    for field in json_fields:
        raw = item.get(field, "{}")
        try:
            item[field] = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            item[field] = {}
    item["enabled"] = bool(item.get("enabled"))
    return item


class InterfaceRepository:
    @staticmethod
    def list(
        keyword: str = "",
        status: str = "",
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[dict], int]:
        page = max(1, int(page or 1))
        page_size = min(50, max(1, int(page_size or 10)))
        offset = (page - 1) * page_size
        keyword = keyword.strip()
        pattern = f"%{keyword}%"
        clauses = ["(? = '' OR code LIKE ? OR name LIKE ? OR api_url LIKE ?)"]
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
                    "SELECT COUNT(*) AS count FROM api_interfaces WHERE " + where, params
                ).fetchone()["count"]
            )
            rows = connection.execute(
                """
                SELECT i.*,
                       COUNT(log.id) AS call_count,
                       COALESCE(SUM(CASE WHEN log.success = 1 THEN 1 ELSE 0 END), 0) AS success_count,
                       MAX(log.created_at) AS last_called_at
                FROM api_interfaces i
                LEFT JOIN interface_calls log ON log.interface_id = i.id
                WHERE """ + where +
                " GROUP BY i.id ORDER BY i.id DESC LIMIT ? OFFSET ?",
                (*params, page_size, offset),
            ).fetchall()
        return [_decode(row, ("request_headers", "request_params")) for row in rows], total

    @staticmethod
    def get(interface_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT i.*,
                       COUNT(log.id) AS call_count,
                       COALESCE(SUM(CASE WHEN log.success = 1 THEN 1 ELSE 0 END), 0) AS success_count,
                       MAX(log.created_at) AS last_called_at
                FROM api_interfaces i
                LEFT JOIN interface_calls log ON log.interface_id = i.id
                WHERE i.id = ?
                GROUP BY i.id
                """,
                (interface_id,),
            ).fetchone()
        return _decode(row, ("request_headers", "request_params"))

    @staticmethod
    def get_by_code(code: str):
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT * FROM api_interfaces WHERE code = ?", (code,)
            ).fetchone()
        return _decode(row, ("request_headers", "request_params"))

    @staticmethod
    def _normalized(values: dict, current: dict | None = None) -> dict:
        current = current or {}
        code = str(values.get("code", current.get("code", ""))).strip().lower()
        name = str(values.get("name", current.get("name", ""))).strip()
        if not CODE_PATTERN.fullmatch(code):
            raise ValueError("编码需以小写字母开头，仅含小写字母、数字和下划线，长度 3—40")
        if not 2 <= len(name) <= 60:
            raise ValueError("接口名称需为 2—60 个字符")
        api_url = _valid_http_url(str(values.get("api_url", current.get("api_url", ""))))
        request_method = str(values.get("request_method", current.get("request_method", "GET"))).upper().strip()
        if request_method not in REQUEST_METHODS:
            raise ValueError("请求方法仅支持 GET 和 POST")
        timeout_seconds = int(values.get("timeout_seconds", current.get("timeout_seconds", 15)) or 15)
        retry_count = int(values.get("retry_count", current.get("retry_count", 0)) or 0)
        if not 3 <= timeout_seconds <= 60:
            raise ValueError("超时时间需为 3—60 秒")
        if not 0 <= retry_count <= 5:
            raise ValueError("重试次数需为 0—5")
        return {
            "code": code,
            "name": name,
            "api_url": api_url,
            "request_method": request_method,
            "request_headers": _headers_json(values.get("request_headers", current.get("request_headers", {}))),
            "request_params": _json_object(values.get("request_params", current.get("request_params", {})), "请求参数"),
            "response_path": str(values.get("response_path", current.get("response_path", ""))).strip(),
            "timeout_seconds": timeout_seconds,
            "retry_count": retry_count,
            "description": str(values.get("description", current.get("description", ""))).strip()[:500],
            "enabled": int(_bool(values.get("enabled", current.get("enabled", True)))),
        }

    @staticmethod
    def create(**values) -> int | None:
        data = InterfaceRepository._normalized(values)
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO api_interfaces
                        (code, name, api_url, request_method, request_headers,
                         request_params, response_path, timeout_seconds, retry_count,
                         description, enabled, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["code"],
                        data["name"],
                        data["api_url"],
                        data["request_method"],
                        data["request_headers"],
                        data["request_params"],
                        data["response_path"],
                        data["timeout_seconds"],
                        data["retry_count"],
                        data["description"],
                        data["enabled"],
                        values.get("created_by"),
                    ),
                )
                connection.commit()
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None

    @staticmethod
    def update(interface_id: int, **values) -> bool:
        current = InterfaceRepository.get(interface_id)
        if not current:
            return False
        data = InterfaceRepository._normalized(values, current)
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    UPDATE api_interfaces SET
                        code = ?, name = ?, api_url = ?, request_method = ?,
                        request_headers = ?, request_params = ?, response_path = ?,
                        timeout_seconds = ?, retry_count = ?, description = ?,
                        enabled = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        data["code"],
                        data["name"],
                        data["api_url"],
                        data["request_method"],
                        data["request_headers"],
                        data["request_params"],
                        data["response_path"],
                        data["timeout_seconds"],
                        data["retry_count"],
                        data["description"],
                        data["enabled"],
                        interface_id,
                    ),
                )
                connection.commit()
            return cursor.rowcount == 1
        except sqlite3.IntegrityError:
            return False

    @staticmethod
    def delete(interface_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute("DELETE FROM api_interfaces WHERE id = ?", (interface_id,))
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def toggle(interface_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                UPDATE api_interfaces SET
                    enabled = CASE enabled WHEN 1 THEN 0 ELSE 1 END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (interface_id,),
            )
            connection.commit()
        return cursor.rowcount == 1


class InterfaceCallRepository:
    @staticmethod
    def record(
        interface_id: int,
        user_id: int | None = None,
        status_code: int = 0,
        success: bool = True,
        error_message: str = "",
        latency_ms: int = 0,
    ) -> int | None:
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO interface_calls
                        (interface_id, user_id, status_code, success, error_message, latency_ms)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        interface_id,
                        user_id,
                        status_code,
                        int(bool(success)),
                        error_message.strip()[:500],
                        max(0, int(latency_ms or 0)),
                    ),
                )
                connection.commit()
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None

    @staticmethod
    def list(
        interface_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        page = max(1, int(page or 1))
        page_size = min(100, max(1, int(page_size or 20)))
        offset = (page - 1) * page_size
        with connection_scope() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM interface_calls WHERE interface_id = ?",
                    (interface_id,),
                ).fetchone()["count"]
            )
            rows = connection.execute(
                """
                SELECT * FROM interface_calls
                WHERE interface_id = ?
                ORDER BY created_at DESC LIMIT ? OFFSET ?
                """,
                (interface_id, page_size, offset),
            ).fetchall()
        return [dict(row) for row in rows], total