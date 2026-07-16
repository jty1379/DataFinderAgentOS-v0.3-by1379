"""瞭源与采集规则 Repository。"""

from __future__ import annotations

import json
import re
import sqlite3
from urllib.parse import urlsplit

from app.models.db import connection_scope

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
PARAM_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
FORBIDDEN_HEADER_NAMES = {
    "authorization",
    "cookie",
    "host",
    "connection",
    "content-length",
    "proxy-authorization",
    "proxy-connection",
}
ALLOWED_HEADER_NAMES = {
    "accept",
    "accept-language",
    "cache-control",
    "pragma",
    "referer",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "sec-fetch-user",
    "upgrade-insecure-requests",
    "user-agent",
}


def _pagination(page: int, page_size: int, maximum: int = 100) -> tuple[int, int, int]:
    page = max(1, int(page or 1))
    page_size = min(maximum, max(1, int(page_size or 10)))
    return page, page_size, (page - 1) * page_size


def _bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _json_object(value, label: str) -> tuple[str, dict]:
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
    normalized = {str(key): value for key, value in parsed.items()}
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":")), normalized


def _headers_json(value) -> str:
    _, headers = _json_object(value, "请求头")
    forbidden = sorted(
        key for key in headers if key.strip().lower() in FORBIDDEN_HEADER_NAMES
    )
    if forbidden:
        raise ValueError("请求头不允许包含：" + "、".join(forbidden))
    unsupported = sorted(
        key for key in headers if key.strip().lower() not in ALLOWED_HEADER_NAMES
    )
    if unsupported:
        raise ValueError("请求头不在安全白名单：" + "、".join(unsupported))
    normalized: dict[str, str] = {}
    for key, raw_value in headers.items():
        if "\r" in key or "\n" in key or not key.strip():
            raise ValueError("请求头名称不正确")
        if isinstance(raw_value, (dict, list, tuple)):
            raise ValueError("请求头值必须是文本")
        text = str(raw_value).strip()
        if "\r" in text or "\n" in text:
            raise ValueError("请求头值不允许包含换行符")
        normalized[key.strip()] = text[:1000]
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def _valid_http_url(value: str) -> str:
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("瞭源 URL 仅支持完整的 http/https 地址")
    if parsed.username or parsed.password:
        raise ValueError("瞭源 URL 不允许携带用户凭据")
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
    if "source_enabled" in item:
        item["source_enabled"] = bool(item["source_enabled"])
    if "default_headers" in item:
        item["headers_json"] = json.dumps(
            item["default_headers"], ensure_ascii=False, indent=2
        )
    if "fixed_params" in item:
        item["fixed_params_json"] = json.dumps(
            item["fixed_params"], ensure_ascii=False, indent=2
        )
    if "request_headers" in item:
        item["headers_json"] = json.dumps(
            item["request_headers"], ensure_ascii=False, indent=2
        )
    return item


class SourceRepository:
    @staticmethod
    def list(keyword: str = "", page: int = 1, page_size: int = 10) -> tuple[list[dict], int]:
        page, page_size, offset = _pagination(page, page_size)
        keyword = keyword.strip()
        pattern = f"%{keyword}%"
        where = "(? = '' OR code LIKE ? OR name LIKE ? OR base_url LIKE ?)"
        params = (keyword, pattern, pattern, pattern)
        with connection_scope() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) AS count FROM lookout_sources WHERE {where}", params
                ).fetchone()["count"]
            )
            rows = connection.execute(
                f"""
                SELECT s.*,
                       (SELECT COUNT(*) FROM collection_rules r WHERE r.source_id = s.id)
                           AS rule_count,
                       (SELECT r.id FROM collection_rules r
                        WHERE r.source_id=s.id AND r.enabled=1 ORDER BY r.id LIMIT 1)
                           AS first_enabled_rule_id,
                       COALESCE(stats.run_count,0) AS run_count,
                       COALESCE(stats.success_count,0) AS success_count,
                       COALESCE(stats.failed_count,0) AS failed_count,
                       COALESCE(stats.avg_latency_ms,0) AS avg_latency_ms,
                       COALESCE(stats.last_collected_at,'') AS last_collected_at,
                       COALESCE((
                           SELECT cr2.error_message
                           FROM collection_runs cr2
                           JOIN collection_rules r2 ON r2.id=cr2.rule_id
                           WHERE r2.source_id=s.id AND cr2.error_message<>''
                           ORDER BY cr2.id DESC LIMIT 1
                       ),'') AS last_error
                FROM lookout_sources s
                LEFT JOIN (
                    SELECT r.source_id,COUNT(cr.id) AS run_count,
                           SUM(CASE WHEN cr.status IN ('success','partial') THEN 1 ELSE 0 END)
                               AS success_count,
                           SUM(CASE WHEN cr.status='failed' THEN 1 ELSE 0 END) AS failed_count,
                           AVG(CASE WHEN cr.started_at IS NOT NULL AND cr.finished_at IS NOT NULL
                               THEN (julianday(cr.finished_at)-julianday(cr.started_at))*86400000 END)
                               AS avg_latency_ms,
                           MAX(COALESCE(cr.finished_at,cr.created_at)) AS last_collected_at
                    FROM collection_rules r
                    LEFT JOIN collection_runs cr ON cr.rule_id=r.id
                    GROUP BY r.source_id
                ) stats ON stats.source_id=s.id
                WHERE {where}
                ORDER BY s.id DESC LIMIT ? OFFSET ?
                """,
                (*params, page_size, offset),
            ).fetchall()
        output = [_decode(row, ("default_headers",)) for row in rows]
        for item in output:
            completed = int(item.get("success_count", 0)) + int(item.get("failed_count", 0))
            item["success_rate"] = round(int(item.get("success_count", 0)) / completed * 100, 1) if completed else 0
            item["avg_latency_ms"] = round(float(item.get("avg_latency_ms", 0) or 0))
        return output, total

    @staticmethod
    def get(source_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT * FROM lookout_sources WHERE id = ?", (source_id,)
            ).fetchone()
        return _decode(row, ("default_headers",))

    @staticmethod
    def create(
        *,
        code: str,
        name: str,
        base_url: str,
        description: str = "",
        headers_json=None,
        default_headers=None,
        enabled: bool = True,
        created_by: int | None = None,
    ) -> int | None:
        code = code.strip()
        name = name.strip()
        if not CODE_PATTERN.fullmatch(code):
            raise ValueError("来源编码需为 3—41 位小写字母、数字或下划线")
        if not 2 <= len(name) <= 50:
            raise ValueError("来源名称需为 2—50 个字符")
        headers = default_headers if default_headers is not None else headers_json
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO lookout_sources
                        (code, name, base_url, description, default_headers,
                         enabled, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        code,
                        name,
                        _valid_http_url(base_url),
                        description.strip()[:300],
                        _headers_json(headers),
                        int(_bool(enabled)),
                        created_by,
                    ),
                )
                connection.commit()
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None

    @staticmethod
    def update(source_id: int, **values) -> bool:
        current = SourceRepository.get(source_id)
        if not current:
            return False
        code = str(values.get("code", current["code"])).strip()
        name = str(values.get("name", current["name"])).strip()
        if not CODE_PATTERN.fullmatch(code) or not 2 <= len(name) <= 50:
            raise ValueError("来源编码或名称格式不正确")
        headers = values.get(
            "default_headers", values.get("headers_json", current["default_headers"])
        )
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    UPDATE lookout_sources
                    SET code = ?, name = ?, base_url = ?, description = ?,
                        default_headers = ?, enabled = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        code,
                        name,
                        _valid_http_url(str(values.get("base_url", current["base_url"]))),
                        str(values.get("description", current["description"])).strip()[:300],
                        _headers_json(headers),
                        int(_bool(values.get("enabled", current["enabled"]))),
                        source_id,
                    ),
                )
                connection.commit()
            return cursor.rowcount == 1
        except sqlite3.IntegrityError:
            return False

    @staticmethod
    def delete(source_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                "DELETE FROM lookout_sources WHERE id = ?", (source_id,)
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def toggle(source_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                UPDATE lookout_sources SET enabled = CASE enabled WHEN 1 THEN 0 ELSE 1 END,
                    updated_at = CURRENT_TIMESTAMP WHERE id = ?
                """,
                (source_id,),
            )
            connection.commit()
        return cursor.rowcount == 1


class RuleRepository:
    SELECT = """
        SELECT r.*, s.code AS source_code, s.name AS source_name,
               s.base_url, s.default_headers, s.enabled AS source_enabled
        FROM collection_rules r JOIN lookout_sources s ON s.id = r.source_id
    """

    @staticmethod
    def list(
        keyword: str = "",
        source_id: int | None = None,
        page: int = 1,
        page_size: int = 10,
        enabled_only: bool = False,
    ) -> tuple[list[dict], int]:
        page, page_size, offset = _pagination(page, page_size)
        keyword = keyword.strip()
        pattern = f"%{keyword}%"
        clauses = ["(? = '' OR r.name LIKE ? OR s.name LIKE ?)"]
        params: list[object] = [keyword, pattern, pattern]
        if source_id:
            clauses.append("r.source_id = ?")
            params.append(int(source_id))
        if enabled_only:
            clauses.extend(["r.enabled = 1", "s.enabled = 1"])
        where = " AND ".join(clauses)
        with connection_scope() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM collection_rules r "
                    "JOIN lookout_sources s ON s.id = r.source_id WHERE " + where,
                    params,
                ).fetchone()["count"]
            )
            rows = connection.execute(
                RuleRepository.SELECT
                + " WHERE "
                + where
                + " ORDER BY r.id DESC LIMIT ? OFFSET ?",
                (*params, page_size, offset),
            ).fetchall()
        fields = ("fixed_params", "request_headers", "parser_config", "default_headers")
        return [_decode(row, fields) for row in rows], total

    @staticmethod
    def get(rule_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                RuleRepository.SELECT + " WHERE r.id = ?", (rule_id,)
            ).fetchone()
        return _decode(
            row, ("fixed_params", "request_headers", "parser_config", "default_headers")
        )

    @staticmethod
    def _normalized(values: dict, current: dict | None = None) -> dict:
        current = current or {}
        result = {
            "source_id": int(values.get("source_id", current.get("source_id", 0))),
            "name": str(values.get("name", current.get("name", ""))).strip(),
            "keyword_param": str(
                values.get("keyword_param", current.get("keyword_param", "word"))
            ).strip(),
            "page_param": str(
                values.get("page_param", current.get("page_param", "pn"))
            ).strip(),
            "page_start": int(values.get("page_start", current.get("page_start", 0))),
            "page_step": int(values.get("page_step", current.get("page_step", 10))),
            "page_size": int(values.get("page_size", current.get("page_size", 12))),
            "parser_type": str(
                values.get("parser_type", current.get("parser_type", "generic_links"))
            ).strip(),
            "enabled": int(_bool(values.get("enabled", current.get("enabled", True)))),
        }
        if not 2 <= len(result["name"]) <= 60:
            raise ValueError("规则名称需为 2—60 个字符")
        if not PARAM_PATTERN.fullmatch(result["keyword_param"]):
            raise ValueError("关键词参数名格式不正确")
        if result["page_param"] and not PARAM_PATTERN.fullmatch(result["page_param"]):
            raise ValueError("分页参数名格式不正确")
        if result["page_start"] < 0 or result["page_step"] < 1:
            raise ValueError("分页起点或步长无效")
        if not 1 <= result["page_size"] <= 100:
            raise ValueError("每页条数需为 1—100")
        if result["parser_type"] not in {"baidu_news", "generic_links", "bing_news", "chinanews"}:
            raise ValueError("不支持的解析器类型")
        fixed = values.get(
            "fixed_params", values.get("params_json", current.get("fixed_params", {}))
        )
        request_headers = values.get(
            "request_headers", values.get("headers_json", current.get("request_headers", {}))
        )
        parser_config = values.get(
            "parser_config", values.get("parser_config_json", current.get("parser_config", {}))
        )
        result["fixed_params"] = _json_object(fixed, "固定参数")[0]
        result["request_headers"] = _headers_json(request_headers)
        result["parser_config"] = _json_object(parser_config, "解析配置")[0]
        return result

    @staticmethod
    def create(**values) -> int | None:
        data = RuleRepository._normalized(values)
        try:
            with connection_scope() as connection:
                source = connection.execute(
                    "SELECT 1 FROM lookout_sources WHERE id = ?", (data["source_id"],)
                ).fetchone()
                if source is None:
                    return None
                cursor = connection.execute(
                    """
                    INSERT INTO collection_rules
                        (source_id, name, keyword_param, page_param, page_start,
                         page_step, page_size, fixed_params, request_headers,
                         parser_type, parser_config, enabled)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    tuple(data[key] for key in (
                        "source_id", "name", "keyword_param", "page_param", "page_start",
                        "page_step", "page_size", "fixed_params", "request_headers",
                        "parser_type", "parser_config", "enabled",
                    )),
                )
                connection.commit()
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None

    @staticmethod
    def update(rule_id: int, **values) -> bool:
        current = RuleRepository.get(rule_id)
        if not current:
            return False
        data = RuleRepository._normalized(values, current)
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    UPDATE collection_rules
                    SET source_id = ?, name = ?, keyword_param = ?, page_param = ?,
                        page_start = ?, page_step = ?, page_size = ?, fixed_params = ?,
                        request_headers = ?, parser_type = ?, parser_config = ?, enabled = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        *(data[key] for key in (
                            "source_id", "name", "keyword_param", "page_param", "page_start",
                            "page_step", "page_size", "fixed_params", "request_headers",
                            "parser_type", "parser_config", "enabled",
                        )),
                        rule_id,
                    ),
                )
                connection.commit()
            return cursor.rowcount == 1
        except sqlite3.IntegrityError:
            return False

    @staticmethod
    def delete(rule_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute("DELETE FROM collection_rules WHERE id = ?", (rule_id,))
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def toggle(rule_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                UPDATE collection_rules SET enabled = CASE enabled WHEN 1 THEN 0 ELSE 1 END,
                    updated_at = CURRENT_TIMESTAMP WHERE id = ?
                """,
                (rule_id,),
            )
            connection.commit()
        return cursor.rowcount == 1
