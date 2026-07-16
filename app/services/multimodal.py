"""多模态服务：生图、生视频、多模态对话。"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import requests

from config.settings import SETTINGS
import logging
LOGGER = logging.getLogger("multimodal")


class MultimodalError(Exception):
    pass


class MultimodalService:
    PROVIDER_VOLCENGINE = "volcengine"
    PROVIDER_ALIYUN = "aliyun"
    PROVIDER_OPENAI = "openai"

    TASK_TYPE_IMAGE = "image"
    TASK_TYPE_VIDEO = "video"
    TASK_TYPE_CHAT = "chat"

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    def __init__(self):
        self.provider = os.environ.get("MULTIMODAL_PROVIDER", self.PROVIDER_VOLCENGINE)
        self.api_key = os.environ.get("MULTIMODAL_API_KEY", "")
        self.api_secret = os.environ.get("MULTIMODAL_API_SECRET", "")
        self.base_url = os.environ.get("MULTIMODAL_BASE_URL", "")
        self._cache_dir = os.path.join(SETTINGS.data_dir, "multimodal")
        os.makedirs(self._cache_dir, exist_ok=True)

    def generate_image(self, prompt: str, style: str = "default", image_size: str = "1024x1024") -> dict:
        task_id = str(uuid.uuid4())
        task_data = {
            "task_id": task_id,
            "type": self.TASK_TYPE_IMAGE,
            "status": self.STATUS_RUNNING,
            "prompt": prompt,
            "style": style,
            "image_size": image_size,
            "result": None,
            "error": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        cache_path = self._get_cache_path(task_id)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(task_data, f)

        try:
            if self.provider == self.PROVIDER_VOLCENGINE:
                result = self._volcengine_generate_image(prompt, style, image_size)
            elif self.provider == self.PROVIDER_ALIYUN:
                result = self._aliyun_generate_image(prompt, style, image_size)
            elif self.provider == self.PROVIDER_OPENAI:
                result = self._openai_generate_image(prompt, image_size)
            else:
                result = {"error": f"Unsupported provider: {self.provider}"}

            if "error" in result:
                task_data["status"] = self.STATUS_FAILED
                task_data["error"] = result["error"]
            else:
                task_data["status"] = self.STATUS_COMPLETED
                task_data["result"] = result
        except Exception as e:
            task_data["status"] = self.STATUS_FAILED
            task_data["error"] = str(e)
            LOGGER.error(f"Multimodal image generation failed: {e}")

        task_data["updated_at"] = time.time()
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(task_data, f)

        return task_data

    def generate_video(self, prompt: str, duration: int = 5) -> dict:
        task_id = str(uuid.uuid4())
        task_data = {
            "task_id": task_id,
            "type": self.TASK_TYPE_VIDEO,
            "status": self.STATUS_RUNNING,
            "prompt": prompt,
            "duration": duration,
            "result": None,
            "error": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        cache_path = self._get_cache_path(task_id)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(task_data, f)

        try:
            if self.provider == self.PROVIDER_VOLCENGINE:
                result = self._volcengine_generate_video(prompt, duration)
            elif self.provider == self.PROVIDER_ALIYUN:
                result = self._aliyun_generate_video(prompt, duration)
            else:
                result = {"error": f"Video generation not supported for provider: {self.provider}"}

            if "error" in result:
                task_data["status"] = self.STATUS_FAILED
                task_data["error"] = result["error"]
            else:
                task_data["status"] = self.STATUS_COMPLETED
                task_data["result"] = result
        except Exception as e:
            task_data["status"] = self.STATUS_FAILED
            task_data["error"] = str(e)
            LOGGER.error(f"Multimodal video generation failed: {e}")

        task_data["updated_at"] = time.time()
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(task_data, f)

        return task_data

    def get_task_status(self, task_id: str) -> dict | None:
        cache_path = self._get_cache_path(task_id)
        if not os.path.exists(cache_path):
            return None
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def list_tasks(self, task_type: str = None, limit: int = 20) -> list:
        tasks = []
        for filename in os.listdir(self._cache_dir):
            if not filename.endswith(".json"):
                continue
            task_id = filename[:-5]
            task = self.get_task_status(task_id)
            if task:
                if task_type and task.get("type") != task_type:
                    continue
                tasks.append(task)
        tasks.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return tasks[:limit]

    def delete_task(self, task_id: str) -> bool:
        cache_path = self._get_cache_path(task_id)
        if os.path.exists(cache_path):
            os.remove(cache_path)
            return True
        return False

    def _get_cache_path(self, task_id: str) -> str:
        return os.path.join(self._cache_dir, f"{task_id}.json")

    def _volcengine_generate_image(self, prompt: str, style: str, image_size: str) -> dict:
        url = self.base_url or "https://image.bytedance.net/api/text2image"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        data = {
            "prompt": prompt,
            "style": style,
            "image_size": image_size,
        }
        response = requests.post(url, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        result = response.json()
        if "data" in result:
            return {"image_url": result["data"].get("url"), "task_id": result.get("task_id")}
        return {"error": result.get("message", "Generation failed")}

    def _volcengine_generate_video(self, prompt: str, duration: int) -> dict:
        url = self.base_url or "https://video.bytedance.net/api/text2video"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        data = {
            "prompt": prompt,
            "duration": duration,
        }
        response = requests.post(url, headers=headers, json=data, timeout=120)
        response.raise_for_status()
        result = response.json()
        if "data" in result:
            return {"video_url": result["data"].get("url"), "task_id": result.get("task_id")}
        return {"error": result.get("message", "Generation failed")}

    def _aliyun_generate_image(self, prompt: str, style: str, image_size: str) -> dict:
        url = self.base_url or "https://dashscope-api.cn-hangzhou.aliyuncs.com/api/text2image"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        data = {
            "model": "wanx-v1",
            "input": {"prompt": prompt},
            "parameters": {"style": style, "size": image_size},
        }
        response = requests.post(url, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        result = response.json()
        if "output" in result:
            return {"image_url": result["output"].get("url")}
        return {"error": result.get("message", "Generation failed")}

    def _aliyun_generate_video(self, prompt: str, duration: int) -> dict:
        url = self.base_url or "https://dashscope-api.cn-hangzhou.aliyuncs.com/api/text2video"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        data = {
            "model": "video-synthesis",
            "input": {"prompt": prompt},
            "parameters": {"duration": duration},
        }
        response = requests.post(url, headers=headers, json=data, timeout=120)
        response.raise_for_status()
        result = response.json()
        if "output" in result:
            return {"video_url": result["output"].get("url")}
        return {"error": result.get("message", "Generation failed")}

    def _openai_generate_image(self, prompt: str, image_size: str) -> dict:
        url = self.base_url or "https://api.openai.com/v1/images/generations"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        data = {
            "prompt": prompt,
            "n": 1,
            "size": image_size,
            "response_format": "url",
        }
        response = requests.post(url, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        result = response.json()
        if "data" in result and result["data"]:
            return {"image_url": result["data"][0].get("url")}
        return {"error": result.get("error", {}).get("message", "Generation failed")}