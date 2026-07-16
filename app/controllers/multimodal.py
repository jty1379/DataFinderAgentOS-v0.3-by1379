"""Multimodal configuration and asynchronous task APIs."""

from __future__ import annotations

from pathlib import Path

import tornado.web

from app.controllers.base import AdminBaseHandler, AdminJsonHandler, UserJsonHandler
from app.models.multimodal import MultimodalConfigRepository, MultimodalTaskRepository
from app.services.multimodal import MultimodalError, MultimodalService
from config.settings import BASE_DIR

IMAGE_STYLES = [
    ("default", "默认风格"),
    ("photo", "写实风格"),
    ("cartoon", "卡通风格"),
    ("anime", "动漫风格"),
    ("oil", "油画风格"),
    ("sketch", "素描风格"),
    ("watercolor", "水彩风格"),
    ("3d", "3D 风格"),
    ("minimal", "极简风格"),
]
IMAGE_SIZES = [
    ("512x512", "512×512"),
    ("1024x1024", "1024×1024"),
    ("1024x1536", "1024×1536"),
    ("1536x1024", "1536×1024"),
]
PROVIDER_OPTIONS = [
    ("minimax", "MiniMax 国内 Token Plan"),
    ("openai_compatible", "OpenAI API 兼容服务"),
]


class AdminMultimodalHandler(AdminBaseHandler):
    required_feature = "multimodal_config"

    def get(self):
        self.render_admin(
            "admin/multimodal.html",
            title="多模态服务 · 零界",
            active_menu="model_engine",
            config=MultimodalConfigRepository.get_config(),
            stats=MultimodalTaskRepository.stats(),
            image_styles=IMAGE_STYLES,
            image_sizes=IMAGE_SIZES,
            provider_options=PROVIDER_OPTIONS,
        )


class AdminMultimodalConfigHandler(AdminBaseHandler):
    required_feature = "multimodal_config"

    def post(self):
        self.require_superadmin()
        try:
            MultimodalConfigRepository.update_config(
                {
                    "enabled": self.get_body_argument("enabled", "0"),
                    "provider": self.get_body_argument(
                        "provider", "openai_compatible"
                    ),
                    "api_key_env": self.get_body_argument("api_key_env", ""),
                    "api_secret_env": self.get_body_argument("api_secret_env", ""),
                    "base_url": self.get_body_argument("base_url", ""),
                    "image_model": self.get_body_argument("image_model", ""),
                    "default_image_size": self.get_body_argument(
                        "default_image_size", "1024x1024"
                    ),
                    "default_video_duration": self.get_body_argument(
                        "default_video_duration", "5"
                    ),
                    "video_enabled": self.get_body_argument("video_enabled", "0"),
                }
            )
            self.redirect_with_message("/admin/multimodal", "多模态配置已更新", "success")
        except (TypeError, ValueError) as exc:
            self.redirect_with_message("/admin/multimodal", str(exc), "error")


def _submit(handler, data: dict, user_id: int) -> dict:
    return MultimodalService.submit(
        str(data.get("task_type") or "image"),
        str(data.get("prompt") or ""),
        user_id=user_id,
        style=str(data.get("style") or "default"),
        image_size=str(data.get("image_size") or ""),
        duration=int(data.get("duration") or 5),
    )


class AdminMultimodalGenerateHandler(AdminJsonHandler):
    required_feature = "multimodal_config"

    def post(self):
        try:
            task = _submit(self, self.json_body(), self.current_user["id"])
        except (TypeError, ValueError, MultimodalError) as exc:
            return self.write_json({"ok": False, "message": str(exc)}, 400)
        return self.write_json(
            {"ok": True, "message": "生成任务已提交", "data": task}, 202
        )


class AdminMultimodalTaskStatusHandler(AdminJsonHandler):
    required_feature = "multimodal_config"

    def get(self, task_id: str):
        task = MultimodalTaskRepository.get(task_id)
        if not task:
            return self.write_json({"ok": False, "message": "任务不存在"}, 404)
        return self.write_json({"ok": True, "data": task})


class AdminMultimodalTaskListHandler(AdminJsonHandler):
    required_feature = "multimodal_config"

    def get(self):
        task_type = self.get_query_argument("type", "")
        return self.write_json(
            {"ok": True, "data": MultimodalTaskRepository.list(task_type, 50)}
        )


class AdminMultimodalTaskDeleteHandler(AdminJsonHandler):
    required_feature = "multimodal_config"

    def post(self, task_id: str):
        if not MultimodalService.delete_task(task_id):
            return self.write_json({"ok": False, "message": "任务不存在"}, 404)
        return self.write_json({"ok": True, "message": "任务已删除"})


class UserMultimodalGenerateHandler(UserJsonHandler):
    def post(self):
        try:
            task = _submit(self, self.json_body(), self.current_user["id"])
        except (TypeError, ValueError, MultimodalError) as exc:
            return self.write_json({"ok": False, "message": str(exc)}, 400)
        return self.write_json(
            {"ok": True, "message": "生成任务已提交", "data": task}, 202
        )


class UserMultimodalTaskStatusHandler(UserJsonHandler):
    def get(self, task_id: str):
        task = MultimodalTaskRepository.get(task_id, self.current_user["id"])
        if not task:
            return self.write_json({"ok": False, "message": "任务不存在"}, 404)
        return self.write_json({"ok": True, "data": task})


class MultimodalAssetHandler(tornado.web.StaticFileHandler):
    def initialize(self):
        self.root = str(BASE_DIR / "data" / "multimodal")

    def validate_absolute_path(self, root: str, absolute_path: str) -> str | None:
        root_path = Path(root).resolve()
        resolved = Path(absolute_path).resolve()
        if root_path not in resolved.parents:
            raise tornado.web.HTTPError(403, reason="Forbidden")
        return super().validate_absolute_path(root, absolute_path)
