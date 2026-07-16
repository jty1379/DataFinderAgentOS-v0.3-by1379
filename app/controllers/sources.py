"""瞭源与采集规则管理。"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from app.controllers.base import AdminBaseHandler
from app.repositories.source_repository import RuleRepository, SourceRepository
from app.services.collector import CollectorService

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
PARAM_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,39}$")
FORBIDDEN_HEADERS = {"authorization", "cookie", "host", "connection", "proxy-authorization"}


def _query_page(handler: AdminBaseHandler, name: str) -> int:
    try:
        return max(1, int(handler.get_query_argument(name, "1")))
    except ValueError:
        return 1


def _body_int(handler: AdminBaseHandler, name: str, default: int = 0) -> int:
    try:
        return int(handler.get_body_argument(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc


def _json_object(raw: str, label: str) -> dict[str, object]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label}必须是合法 JSON 对象") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}必须是 JSON 对象")
    return value


def _headers_json(raw: str) -> str:
    headers = _json_object(raw, "请求头")
    normalized: dict[str, str] = {}
    for key, value in headers.items():
        name = str(key).strip()
        if name.lower() in FORBIDDEN_HEADERS:
            raise ValueError(f"出于安全原因不能配置请求头 {name}")
        if not name or "\n" in name or "\r" in name:
            raise ValueError("请求头名称不正确")
        text = str(value).strip()
        if "\n" in text or "\r" in text:
            raise ValueError("请求头值不能包含换行")
        normalized[name] = text
    return json.dumps(normalized, ensure_ascii=False)


def _result_message(result, success: str) -> tuple[str, str]:
    if isinstance(result, tuple):
        ok, message = result
        return str(message), "success" if ok else "error"
    return (success, "success") if result else ("操作失败，请检查关联数据", "error")


class AdminSourcesHandler(AdminBaseHandler):
    required_feature = "collection_management"

    def get(self):
        keyword = self.get_query_argument("q", "").strip()
        source_page = _query_page(self, "source_page")
        rule_page = _query_page(self, "rule_page")
        sources, source_total = SourceRepository.list(
            keyword=keyword, page=source_page, page_size=8
        )
        rules, rule_total = RuleRepository.list(
            keyword=keyword, page=rule_page, page_size=8
        )
        all_sources, _ = SourceRepository.list(page=1, page_size=200)
        for source in [*sources, *all_sources]:
            source["headers_json"] = json.dumps(
                source.get("default_headers", {}), ensure_ascii=False, indent=2
            )
        for rule in rules:
            rule["fixed_param_count"] = len(rule.get("fixed_params", {}))
            rule["header_count"] = len(rule.get("request_headers", {}))
            rule["fixed_params_json"] = json.dumps(
                rule.get("fixed_params", {}), ensure_ascii=False, indent=2
            )
            rule["headers_json"] = json.dumps(
                rule.get("request_headers", {}), ensure_ascii=False, indent=2
            )
        self.render_admin(
            "admin/sources.html",
            title="瞭源管理 · 零界",
            active_menu="collection_management",
            sources=sources,
            rules=rules,
            all_sources=all_sources,
            keyword=keyword,
            source_page=source_page,
            source_pages=max(1, (source_total + 7) // 8),
            source_total=source_total,
            rule_page=rule_page,
            rule_pages=max(1, (rule_total + 7) // 8),
            rule_total=rule_total,
            can_write=True,
        )

    async def post(self):
        action = self.get_body_argument("action", "")
        try:
            if action in {"create_source", "update_source"}:
                source_id = _body_int(self, "source_id") if action == "update_source" else None
                name = self.get_body_argument("name", "").strip()
                code = self.get_body_argument("code", "").strip()
                base_url = self.get_body_argument("base_url", "").strip()
                description = self.get_body_argument("description", "").strip()[:300]
                enabled = self.get_body_argument("enabled", "1") == "1"
                if not 2 <= len(name) <= 40 or not CODE_PATTERN.fullmatch(code):
                    raise ValueError("来源名称或编码格式不正确")
                parsed = urlparse(base_url)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    raise ValueError("来源地址必须是有效的 HTTP/HTTPS URL")
                values = dict(
                    name=name,
                    code=code,
                    base_url=base_url,
                    description=description,
                    headers_json=_headers_json(self.get_body_argument("headers_json", "{}")),
                    enabled=enabled,
                )
                if source_id:
                    result = SourceRepository.update(source_id=source_id, **values)
                    message, level = _result_message(result, "瞭源信息已更新")
                else:
                    result = SourceRepository.create(
                        created_by=self.current_user["id"], **values
                    )
                    message, level = _result_message(result, "瞭源创建成功")
                return self.redirect_with_message("/admin/sources", message, level)

            if action in {"toggle_source", "delete_source"}:
                source_id = _body_int(self, "source_id")
                if action == "toggle_source":
                    result = SourceRepository.toggle(source_id)
                    message, level = _result_message(result, "瞭源状态已更新")
                else:
                    result = SourceRepository.delete(source_id)
                    message, level = _result_message(result, "瞭源已删除")
                return self.redirect_with_message("/admin/sources", message, level)

            if action in {"create_rule", "update_rule"}:
                rule_id = _body_int(self, "rule_id") if action == "update_rule" else None
                source_id = _body_int(self, "source_id")
                name = self.get_body_argument("name", "").strip()
                keyword_param = self.get_body_argument("keyword_param", "word").strip()
                page_param = self.get_body_argument("page_param", "pn").strip()
                page_step = _body_int(self, "page_step", 10)
                page_size = _body_int(self, "page_size", 12)
                enabled = self.get_body_argument("enabled", "1") == "1"
                if not 2 <= len(name) <= 50:
                    raise ValueError("规则名称需为 2—50 个字符")
                if not PARAM_PATTERN.fullmatch(keyword_param) or not PARAM_PATTERN.fullmatch(page_param):
                    raise ValueError("关键词或分页参数名不正确")
                if not 1 <= page_step <= 100 or not 1 <= page_size <= 50:
                    raise ValueError("分页步长或每页数量超出允许范围")
                fixed_params = _json_object(
                    self.get_body_argument("fixed_params_json", "{}"), "固定参数"
                )
                values = dict(
                    source_id=source_id,
                    name=name,
                    keyword_param=keyword_param,
                    page_param=page_param,
                    page_step=page_step,
                    page_size=page_size,
                    fixed_params=fixed_params,
                    headers_json=_headers_json(
                        self.get_body_argument("headers_json", "{}")
                    ),
                    enabled=enabled,
                )
                if rule_id:
                    result = RuleRepository.update(rule_id=rule_id, **values)
                    message, level = _result_message(result, "采集规则已更新")
                else:
                    result = RuleRepository.create(**values)
                    message, level = _result_message(result, "采集规则创建成功")
                return self.redirect_with_message("/admin/sources", message, level)

            if action in {"toggle_rule", "delete_rule", "test_rule"}:
                rule_id = _body_int(self, "rule_id")
                if action == "toggle_rule":
                    result = RuleRepository.toggle(rule_id)
                    message, level = _result_message(result, "采集规则状态已更新")
                elif action == "delete_rule":
                    result = RuleRepository.delete(rule_id)
                    message, level = _result_message(result, "采集规则已删除")
                else:
                    rule = RuleRepository.get(rule_id)
                    if not rule or not rule.get("enabled") or not rule.get("source_enabled"):
                        raise ValueError("采集规则或所属瞭源不可用")
                    items = await CollectorService.collect(rule, "四川", page=1, page_size=3)
                    message, level = f"规则测试成功，获取到 {len(items)} 条公开结果", "success"
                return self.redirect_with_message("/admin/sources", message, level)

            raise ValueError("未知操作")
        except (ValueError, RuntimeError) as exc:
            self.redirect_with_message("/admin/sources", str(exc), "error")
