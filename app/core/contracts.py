"""冻结 JSON、分页、SSE 和卡片公共数据结构。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

SSE_EVENTS = frozenset({"meta", "delta", "card", "audio", "error", "done"})
CARD_TYPES = frozenset({"text", "kpi", "table", "line_chart", "bar_chart", "pie_chart", "weather", "music", "news", "image", "video"})


def iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def success_response(data: Any = None, message: str = "ok", request_id: str = "") -> dict:
    return {"success": True, "data": data if data is not None else {}, "message": message, "request_id": request_id}


def error_response(code: str, message: str, request_id: str = "") -> dict:
    return {"success": False, "error": {"code": code, "message": message, "request_id": request_id}}


def pagination(items: list, page: int, page_size: int, total: int) -> dict:
    return {"items": items, "page": int(page), "page_size": int(page_size), "total": int(total)}


def card(card_type: str, payload: dict) -> dict:
    if card_type not in CARD_TYPES:
        raise ValueError(f"未知卡片类型: {card_type}")
    return {"type": card_type, "data": payload, "created_at": iso_now()}


def sse_event(event: str, data: Any, request_id: str = "") -> str:
    if event not in SSE_EVENTS:
        raise ValueError(f"未知 SSE 事件: {event}")
    payload = {"data": data, "request_id": request_id, "timestamp": iso_now()}
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
