"""用户会话 PDF 导出控制器。"""

from __future__ import annotations

from urllib.parse import quote

import tornado.web

from app.controllers.base import UserJsonHandler
from app.models.conversation import ConversationRepository
from app.services.pdf_export import PdfExportError, build_conversation_pdf


class ConversationPdfExportHandler(UserJsonHandler):
    def get(self, conversation_id: str) -> None:
        conversation = ConversationRepository.get_for_user(int(conversation_id), self.current_user["id"])
        if not conversation:
            raise tornado.web.HTTPError(404, reason="会话不存在或不属于当前用户")
        try:
            content = build_conversation_pdf(
                conversation,
                ConversationRepository.messages(conversation["id"], self.current_user["id"]),
                self.current_user["username"],
            )
        except PdfExportError as exc:
            raise tornado.web.HTTPError(500, reason=str(exc)) from exc
        filename = f"问数会话-{conversation['title'][:24]}.pdf"
        self.set_header("Content-Type", "application/pdf")
        self.set_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
        self.set_header("Content-Length", str(len(content)))
        self.finish(content)
