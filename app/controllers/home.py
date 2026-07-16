"""用户侧智能工作台、会话 API 与管理端工作台。"""

from __future__ import annotations

import asyncio
import json

import tornado.web
from tornado.iostream import StreamClosedError

from app.controllers.base import AdminBaseHandler, BaseHandler, UserJsonHandler
from app.models.conversation import ConversationRepository
from app.models.dashboard import DashboardRepository
from app.models.digital_employee import DigitalEmployeeRepository
from app.models.model_engine import ModelRepository
from app.models.rbac import RoleRepository
from app.services.system_settings import SystemSettingsService
from app.services.user_chat import UserChatError, UserChatService


def _integer(value) -> int | None:
    try:
        number = int(value or 0)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


class UserIndexHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        if self.current_user["role_scope"] != "user" or not RoleRepository.has_feature(
            self.current_user["role_id"], "user_portal"
        ):
            raise tornado.web.HTTPError(403)
        models, _ = ModelRepository.list(status="enabled", page_size=100)
        models = [item for item in models if item["model_type"] in {"text", "multimodal"}]
        employees, _ = DigitalEmployeeRepository.list(status="enabled", page_size=50)
        employees = [item for item in employees if item["code"] != "collection_specialist"]
        self.render(
            "index.html",
            title="智能问数 · 瞭望与问数系统",
            user=self.current_user,
            models=models,
            default_model=SystemSettingsService.get_default_model(),
            employees=employees,
            conversations=ConversationRepository.list_for_user(self.current_user["id"]),
        )


class UserConversationHandler(UserJsonHandler):
    def get(self, conversation_id: str):
        item = ConversationRepository.get_for_user(int(conversation_id), self.current_user["id"])
        if not item:
            raise tornado.web.HTTPError(404)
        self.write_json({
            "ok": True,
            "conversation": item,
            "messages": ConversationRepository.messages(item["id"], self.current_user["id"]),
        })

    def delete(self, conversation_id: str):
        if not ConversationRepository.delete(int(conversation_id), self.current_user["id"]):
            raise tornado.web.HTTPError(404)
        self.write_json({"ok": True, "message": "会话已删除"})


class UserChatHandler(UserJsonHandler):
    async def post(self):
        try:
            self.write_json(await UserChatService.process(
                self.json_body(), self.current_user["id"]
            ))
        except UserChatError as exc:
            self.write_json({
                "ok": False, "message": str(exc),
                "conversation_id": exc.conversation_id,
            }, exc.status)


class UserChatStreamHandler(UserJsonHandler):
    """SSE transport for progressive user-side replies."""

    async def post(self):
        self.set_header("Content-Type", "text/event-stream; charset=UTF-8")
        self.set_header("Cache-Control", "no-cache, no-transform")
        self.set_header("X-Accel-Buffering", "no")

        async def emit(event: str, data: dict):
            self.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n")
            await self.flush()

        task = None
        try:
            await emit("meta", {"status": "正在识别意图并查询数据", "request_id": self.request_id})
            queue = asyncio.Queue()
            task = asyncio.create_task(UserChatService.process(
                self.json_body(), self.current_user["id"], queue.put_nowait
            ))
            streamed = False
            while not task.done():
                try:
                    piece = await asyncio.wait_for(queue.get(), timeout=0.05)
                    streamed = True
                    await emit("delta", {"text": piece})
                except TimeoutError:
                    continue
            result = await task
            while not queue.empty():
                streamed = True
                await emit("delta", {"text": queue.get_nowait()})
            message = result["message"]
            if message["content_type"] == "text" and not streamed:
                text = message["content"]
                for start in range(0, len(text), 24):
                    await emit("delta", {"text": text[start:start + 24]})
            else:
                await emit("card", message)
            metadata = message.get("metadata") or {}
            usage = metadata.get("usage") or {}
            final_meta = {
                "total_tokens": int(usage.get("total_tokens") or 0),
                "elapsed_seconds": float(metadata.get("elapsed_seconds") or 0),
                "source": metadata.get("employee") or metadata.get("model") or "问数分析器",
            }
            await emit("done", {"ok": True, "usage": final_meta, "conversation": result["conversation"]})
        except UserChatError as exc:
            await emit("error", {
                "message": str(exc), "conversation_id": exc.conversation_id,
            })
        except StreamClosedError:
            if task and not task.done():
                task.cancel()
            return
        self.finish()


class AdminIndexHandler(AdminBaseHandler):
    required_feature = "dashboard"

    def get(self):
        dashboard = DashboardRepository.overview()
        self.render_admin(
            "admin/index.html",
            title="管理工作台 · 瞭望与问数系统",
            active_menu="dashboard",
            dashboard=dashboard,
            user_count=dashboard["metrics"]["user_count"],
        )
