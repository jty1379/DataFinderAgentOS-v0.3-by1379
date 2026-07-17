"""用户侧智能工作台、会话 API 与管理端工作台。"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import tornado.web
from tornado.iostream import StreamClosedError

from app.controllers.base import AdminBaseHandler, BaseHandler, UserJsonHandler
from app.models.conversation import ConversationRepository
from app.models.dashboard import DashboardRepository
from app.models.digital_employee import DigitalEmployeeRepository
from app.models.model_engine import ModelRepository
from app.models.rbac import RoleRepository
from app.services.system_settings import SystemSettingsService
from app.services.tts import TTSService
from app.services.user_chat import UserChatError, UserChatService
from config.settings import BASE_DIR

UPLOAD_ROOT = BASE_DIR / "data" / "uploads"
ALLOWED_IMAGE_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}
ALLOWED_DOC_TYPES = {
    "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "markdown": "text/markdown; charset=utf-8",
}
ATTACHMENT_TYPES = {**ALLOWED_IMAGE_TYPES, **ALLOWED_DOC_TYPES}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


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
        capabilities = {
            "vision": bool(ModelRepository.get_for_capability("vision")),
            "image": bool(ModelRepository.get_for_capability("image")),
            "video": bool(ModelRepository.get_for_capability("video")),
            "audio": bool(TTSService.is_enabled()),
        }
        self.render(
            "index.html",
            title="智能问数 · 零界",
            user=self.current_user,
            models=models,
            default_model=SystemSettingsService.get_default_model(),
            employees=employees,
            capabilities=capabilities,
            capabilities_json=json.dumps(capabilities),
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
            title="管理工作台 · 零界",
            active_menu="dashboard",
            dashboard=dashboard,
            user_count=dashboard["metrics"]["user_count"],
        )


class UserUploadHandler(UserJsonHandler):
    """用户端附件上传：支持图片（视觉理解）与 PDF/TXT/Markdown 文档。"""

    def post(self):
        files = self.request.files.get("file") or []
        if not files:
            return self.write_json({"ok": False, "message": "请选择要上传的文件"}, 400)
        upload = files[0]
        original = str(upload.get("filename") or "").strip()
        content_type = str(upload.get("content_type") or "").lower()
        body = upload.get("body") or b""
        extension = original.rsplit(".", 1)[-1].lower() if "." in original else ""
        if extension in ALLOWED_IMAGE_TYPES:
            if not content_type.startswith("image/"):
                return self.write_json({"ok": False, "message": "仅支持 PNG/JPG/WEBP/GIF 图片"}, 400)
            kind = "image"
        elif extension in ALLOWED_DOC_TYPES:
            kind = "doc"
        else:
            return self.write_json({"ok": False, "message": "仅支持图片或 PDF/TXT/Markdown 文件"}, 400)
        if not 0 < len(body) <= MAX_UPLOAD_BYTES:
            return self.write_json({"ok": False, "message": "文件为空或超过 8MB 限制"}, 400)
        user_id = int(self.current_user["id"])
        target_dir = UPLOAD_ROOT / str(user_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.{extension}"
        (target_dir / filename).write_bytes(body)
        return self.write_json({
            "ok": True,
            "message": "上传成功",
            "url": f"/api/uploads/{user_id}/{filename}",
            "name": original[:120],
            "kind": kind,
        })


class UserUploadAssetHandler(BaseHandler):
    """仅向文件所有者本人回传上传的附件。"""

    @tornado.web.authenticated
    def get(self, user_id: str, filename: str):
        if int(user_id) != int(self.current_user["id"]):
            raise tornado.web.HTTPError(403)
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if extension not in ATTACHMENT_TYPES:
            raise tornado.web.HTTPError(404)
        root = UPLOAD_ROOT.resolve()
        target = (UPLOAD_ROOT / user_id / filename).resolve()
        if root not in target.parents or not target.is_file():
            raise tornado.web.HTTPError(404)
        self.set_header("Content-Type", ATTACHMENT_TYPES[extension])
        self.set_header("Cache-Control", "private, max-age=86400")
        self.finish(target.read_bytes())
