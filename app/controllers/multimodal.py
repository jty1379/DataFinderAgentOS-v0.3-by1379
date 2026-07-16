"""多模态服务控制器。"""

from __future__ import annotations

import json

import tornado

from app.controllers.base import AdminBaseHandler, AdminJsonHandler, UserJsonHandler
from app.models.multimodal import MultimodalCallRepository, MultimodalConfigRepository
from app.services.multimodal import MultimodalService

IMAGE_STYLES = [
    ("default", "默认风格"),
    ("photo", "写实风格"),
    ("cartoon", "卡通风格"),
    ("anime", "动漫风格"),
    ("oil", "油画风格"),
    ("sketch", "素描风格"),
    ("watercolor", "水彩风格"),
    ("3d", "3D风格"),
    ("pixel", "像素风格"),
    ("cyberpunk", "赛博朋克"),
    ("minimal", "极简风格"),
]

IMAGE_SIZES = [
    ("512x512", "512×512"),
    ("1024x1024", "1024×1024"),
    ("1024x1536", "1024×1536"),
    ("1536x1024", "1536×1024"),
    ("2048x2048", "2048×2048"),
]

PROVIDER_OPTIONS = [
    ("volcengine", "火山引擎"),
    ("aliyun", "阿里云"),
    ("openai", "OpenAI"),
]


class AdminMultimodalHandler(AdminBaseHandler):
    required_feature = "multimodal_config"

    def get(self):
        config = MultimodalConfigRepository.get_config()
        stats = MultimodalCallRepository.get_stats()
        self.render_admin(
            "admin/multimodal.html",
            title="多模态服务",
            active_menu="multimodal_config",
            config=config,
            stats=stats,
            image_styles=IMAGE_STYLES,
            image_sizes=IMAGE_SIZES,
            provider_options=PROVIDER_OPTIONS,
        )


class AdminMultimodalConfigHandler(AdminJsonHandler):
    required_feature = "multimodal_config"

    def post(self):
        data = self.get_json_body()
        config = MultimodalConfigRepository.update_config(data)
        self.write_json({"ok": True, "data": config})


class AdminMultimodalGenerateHandler(AdminJsonHandler):
    required_feature = "multimodal_config"

    def post(self):
        data = self.get_json_body()
        task_type = data.get("task_type", "image")
        prompt = data.get("prompt", "").strip()
        style = data.get("style", "default")
        image_size = data.get("image_size", "1024x1024")
        duration = data.get("duration", 5)

        if not prompt:
            self.write_json({"ok": False, "message": "请输入提示词"})
            return

        service = MultimodalService()
        try:
            if task_type == "image":
                result = service.generate_image(prompt, style, image_size)
            elif task_type == "video":
                result = service.generate_video(prompt, duration)
            else:
                self.write_json({"ok": False, "message": f"不支持的任务类型: {task_type}"})
                return

            MultimodalCallRepository.create_call(task_type, result["task_id"], prompt)
            if result["status"] == "completed":
                MultimodalCallRepository.update_call(result["task_id"], "completed", json.dumps(result["result"]))
            else:
                MultimodalCallRepository.update_call(result["task_id"], "failed", result.get("error", ""))

            self.write_json({"ok": True, "data": result})
        except Exception as e:
            self.write_json({"ok": False, "message": str(e)})


class AdminMultimodalTaskStatusHandler(AdminJsonHandler):
    required_feature = "multimodal_config"

    def get(self, task_id):
        service = MultimodalService()
        task = service.get_task_status(task_id)
        if task:
            self.write_json({"ok": True, "data": task})
        else:
            self.write_json({"ok": False, "message": "任务不存在"})


class AdminMultimodalTaskListHandler(AdminJsonHandler):
    required_feature = "multimodal_config"

    def get(self):
        task_type = self.get_argument("type", None)
        tasks = MultimodalCallRepository.list_calls(task_type=task_type, limit=50)
        self.write_json({"ok": True, "data": tasks})


class AdminMultimodalTaskDeleteHandler(AdminJsonHandler):
    required_feature = "multimodal_config"

    def post(self, task_id):
        service = MultimodalService()
        db_success = MultimodalCallRepository.delete_call(task_id)
        fs_success = service.delete_task(task_id)
        if db_success or fs_success:
            self.write_json({"ok": True})
        else:
            self.write_json({"ok": False, "message": "删除失败"})


class UserMultimodalGenerateHandler(UserJsonHandler):
    def post(self):
        data = self.get_json_body()
        task_type = data.get("task_type", "image")
        prompt = data.get("prompt", "").strip()
        style = data.get("style", "default")
        image_size = data.get("image_size", "1024x1024")
        duration = data.get("duration", 5)

        if not prompt:
            self.write_json({"ok": False, "message": "请输入提示词"})
            return

        service = MultimodalService()
        try:
            if task_type == "image":
                result = service.generate_image(prompt, style, image_size)
            elif task_type == "video":
                result = service.generate_video(prompt, duration)
            else:
                self.write_json({"ok": False, "message": f"不支持的任务类型: {task_type}"})
                return

            self.write_json({"ok": True, "data": result})
        except Exception as e:
            self.write_json({"ok": False, "message": str(e)})