"""Administrative conversation search, lifecycle and export."""

from __future__ import annotations

import math
from datetime import date
from urllib.parse import quote

import tornado.web

from app.controllers.admin.common import pager_context, positive_integers, query_page
from app.controllers.base import AdminBaseHandler
from app.models.conversation import ConversationRepository
from app.models.digital_employee import DigitalEmployeeRepository
from app.models.model_engine import ModelRepository
from app.models.user import UserRepository
from app.services.pdf_export import PdfExportError, build_conversation_pdf


def _date(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("日期格式应为 YYYY-MM-DD") from exc


class AdminSessionsHandler(AdminBaseHandler):
    required_feature = "session_management"

    def get(self) -> None:
        if not self.current_user.get("is_superadmin"):
            raise tornado.web.HTTPError(403, reason="仅超级管理员可查看完整会话")
        filters = {
            "keyword": self.get_query_argument("q", "").strip(),
            "user_id": self._query_id("user_id"),
            "model_id": self._query_id("model_id"),
            "employee_id": self._query_id("employee_id"),
            "status": self.get_query_argument("status", "").strip(),
            "start_date": _date(self.get_query_argument("start_date", "")),
            "end_date": _date(self.get_query_argument("end_date", "")),
        }
        if filters["status"] not in {"", "active", "archived"}:
            filters["status"] = ""
        page = query_page(self)
        conversations, total = ConversationRepository.admin_list(
            **filters, page=page, page_size=20
        )
        pages = max(1, math.ceil(total / 20))
        pager = pager_context(
            "/admin/sessions",
            {"page": min(page, pages), "total": total, "total_pages": pages},
            q=filters["keyword"],
            user_id=filters["user_id"],
            model_id=filters["model_id"],
            employee_id=filters["employee_id"],
            status=filters["status"],
            start_date=filters["start_date"],
            end_date=filters["end_date"],
        )
        models, _ = ModelRepository.list(page=1, page_size=100)
        employees, _ = DigitalEmployeeRepository.list(page=1, page_size=100)
        self.render_admin(
            "admin/sessions.html",
            title="会话管理 · 零界",
            active_menu="session_management",
            conversations=conversations,
            users=UserRepository.list_users(),
            models=models,
            employees=employees,
            pager=pager,
            filters=filters,
        )

    def post(self) -> None:
        self.require_superadmin()
        action = self.get_body_argument("action", "")
        ids = positive_integers(self.get_body_arguments("conversation_ids"))
        single = self.get_body_argument("conversation_id", "")
        if single.isdecimal() and int(single) > 0:
            ids = sorted({*ids, int(single)})
        if not ids:
            return self.redirect_with_message("/admin/sessions", "请至少选择一个会话", "error")
        if action in {"delete", "batch_delete"}:
            changed = ConversationRepository.batch_delete_for_admin(ids)
            message = f"已删除 {changed} 个会话"
        elif action in {"archive", "unarchive"}:
            changed = ConversationRepository.set_archived(ids, action == "archive")
            message = f"已{'归档' if action == 'archive' else '取消归档'} {changed} 个会话"
        else:
            return self.redirect_with_message("/admin/sessions", "未知操作", "error")
        self.redirect_with_message("/admin/sessions", message, "success")

    def _query_id(self, name: str) -> int | None:
        value = self.get_query_argument(name, "").strip()
        return int(value) if value.isdecimal() and int(value) > 0 else None


class AdminMessagesHandler(AdminBaseHandler):
    required_feature = "session_management"

    def get(self) -> None:
        self.require_superadmin()
        conversation_id = self.get_query_argument("conversation_id", "").strip()
        conversation = (
            ConversationRepository._get_for_admin(int(conversation_id))
            if conversation_id.isdecimal()
            else None
        )
        if not conversation:
            return self.redirect_with_message("/admin/sessions", "会话不存在", "error")
        self.render_admin(
            "admin/messages.html",
            title="对话详情 · 零界",
            active_menu="session_management",
            conversation=conversation,
            messages=ConversationRepository._messages_for_admin(conversation["id"]),
        )


class AdminConversationPdfExportHandler(AdminBaseHandler):
    required_feature = "session_management"

    def get(self, conversation_id: str) -> None:
        self.require_superadmin()
        conversation = ConversationRepository._get_for_admin(int(conversation_id))
        if not conversation:
            raise tornado.web.HTTPError(404, reason="会话不存在")
        try:
            content = build_conversation_pdf(
                conversation,
                ConversationRepository._messages_for_admin(conversation["id"]),
                conversation["user_name"],
            )
        except PdfExportError as exc:
            raise tornado.web.HTTPError(500, reason=str(exc)) from exc
        filename = f"后台会话-{conversation['title'][:24]}.pdf"
        self.set_header("Content-Type", "application/pdf")
        self.set_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
        self.set_header("Content-Length", str(len(content)))
        self.finish(content)
