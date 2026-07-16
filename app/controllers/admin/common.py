"""后台表单校验、分页和树形数据等无状态公共函数。"""

from __future__ import annotations

import re
import urllib.parse

import tornado.web

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff]{3,20}$")
CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
ICON_PATTERN = re.compile(r"^layui-icon-[a-z0-9-]+$")


def integer(handler: tornado.web.RequestHandler, name: str, default: int = 0) -> int:
    """读取整数表单字段并给出可展示的校验错误。"""
    try:
        return int(handler.get_body_argument(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc


def positive_integers(values: list[str]) -> list[int]:
    """忽略非法值并返回去重、排序后的正整数。"""
    result: set[int] = set()
    for value in values:
        if value.isdecimal() and int(value) > 0:
            result.add(int(value))
    return sorted(result)


def query_page(handler: tornado.web.RequestHandler) -> int:
    try:
        return max(1, int(handler.get_query_argument("page", "1")))
    except ValueError:
        return 1


def pager_context(path: str, pager: dict, **filters: object) -> dict:
    page = int(pager.get("page", 1))
    pages = max(1, int(pager.get("total_pages", pager.get("pages", 1))))
    clean = {key: value for key, value in filters.items() if value not in (None, "", 0, "0")}

    def page_url(number: int) -> str:
        return f"{path}?{urllib.parse.urlencode({**clean, 'page': number})}"

    start = max(1, min(page - 2, pages - 4))
    end = min(pages, start + 4)
    start = max(1, end - 4)
    result = dict(pager)
    result.update(
        page=page,
        pages=pages,
        total_pages=pages,
        page_links=[
            {"number": number, "url": page_url(number), "current": number == page}
            for number in range(start, end + 1)
        ],
        prev_url=page_url(page - 1) if page > 1 else "",
        next_url=page_url(page + 1) if page < pages else "",
    )
    return result


def layui_feature_tree(nodes: list[dict], ancestor_enabled: bool = True) -> list[dict]:
    result = []
    for node in nodes:
        available = ancestor_enabled and bool(node.get("enabled"))
        result.append(
            {
                "id": int(node["id"]),
                "title": f"{node['name']}（{node['code']}）",
                "disabled": not available,
                "spread": True,
                "children": layui_feature_tree(node.get("children", []), available),
            }
        )
    return result


def validate_text(value: str, label: str, minimum: int = 1, maximum: int = 40) -> str:
    value = value.strip()
    if not minimum <= len(value) <= maximum:
        raise ValueError(f"{label}长度需为 {minimum}—{maximum} 个字符")
    return value
