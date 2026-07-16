"""后台会话管理控制器。"""

import math

from app.controllers.admin.common import integer, pager_context, query_page
from app.controllers.base import AdminBaseHandler
from app.models.conversation import ConversationRepository
from app.models.user import UserRepository


def _pagination(page: int, page_size: int, total: int) -> dict:
    safe_size = min(max(int(page_size or 20), 1), 100)
    total_pages = max(1, math.ceil(total / safe_size))
    safe_page = min(max(int(page or 1), 1), total_pages)
    return {
        "page": safe_page,
        "page_size": safe_size,
        "total": total,
        "total_pages": total_pages,
        "has_prev": safe_page > 1,
        "has_next": safe_page < total_pages,
    }


class AdminSessionsHandler(AdminBaseHandler):
    required_feature = "session_management"

    def get(self) -> None:
        user_id = self.get_query_argument("user_id", "").strip()
        keyword = self.get_query_argument("q", "").strip()
        user_id_int = int(user_id) if user_id.isdecimal() else None
        
        all_users = UserRepository.list_users()
        
        if self.current_user.get("is_superadmin"):
            conversations = ConversationRepository._list_all_for_admin(user_id_int, keyword, query_page(self), 20)
        else:
            conversations = []
        
        pager = _pagination(query_page(self), 20, len(conversations))
        
        self.render_admin(
            "admin/sessions.html",
            title="会话管理 · 瞭望与问数系统",
            active_menu="session_management",
            conversations=conversations,
            users=all_users,
            pager=pager_context("/admin/sessions", pager, q=keyword, user_id=user_id),
            keyword=keyword,
            selected_user_id=user_id_int or 0,
        )

    def post(self) -> None:
        self.require_superadmin()
        action = self.get_body_argument("action", "")
        try:
            handlers = {
                "delete": self._delete,
                "batch_delete": self._batch_delete,
            }
            if action not in handlers:
                raise ValueError("未知操作")
            message, level = handlers[action]()
            self.redirect_with_message("/admin/sessions", message, level)
        except ValueError as exc:
            self.redirect_with_message("/admin/sessions", str(exc), "error")

    def _delete(self) -> tuple[str, str]:
        conversation_id = integer(self, "conversation_id")
        if not ConversationRepository._delete_for_admin(conversation_id):
            raise ValueError("会话不存在或删除失败")
        return "会话已删除", "success"

    def _batch_delete(self) -> tuple[str, str]:
        conversation_ids = self.get_body_arguments("conversation_ids")
        if not conversation_ids:
            raise ValueError("请至少选择一个会话")
        deleted = 0
        for cid in conversation_ids:
            try:
                if ConversationRepository._delete_for_admin(int(cid)):
                    deleted += 1
            except ValueError:
                continue
        return f"已删除 {deleted} 个会话", "success"


class AdminMessagesHandler(AdminBaseHandler):
    required_feature = "session_management"

    def get(self) -> None:
        conversation_id = self.get_query_argument("conversation_id", "").strip()
        if not conversation_id.isdecimal():
            self.redirect("/admin/sessions")
            return
        
        conversation_id_int = int(conversation_id)
        conversation = ConversationRepository._get_for_admin(conversation_id_int)
        
        if not conversation:
            self.redirect("/admin/sessions")
            return
        
        messages = ConversationRepository._messages_for_admin(conversation_id_int)
        
        self.render_admin(
            "admin/messages.html",
            title="对话详情 · 瞭望与问数系统",
            active_menu="session_management",
            conversation=conversation,
            messages=messages,
        )