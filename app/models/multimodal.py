"""Database-backed configuration and task persistence for multimodal generation."""

from __future__ import annotations

import json
import re
import uuid
from urllib.parse import urlsplit

from app.models.db import connection_scope
from app.models.model_engine import ModelRepository

ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{1,79}$")
IMAGE_SIZES = {"512x512", "1024x1024", "1024x1536", "1536x1024"}


def _task(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    for field in ("parameters", "result"):
        try:
            item[field] = json.loads(item.get(field) or "{}")
        except json.JSONDecodeError:
            item[field] = {}
    prompt = str(item.get("prompt") or "").strip()
    if prompt and not re.search(r"[^?？\s\ufffd]", prompt):
        prompt = f"{'图片' if item.get('task_type') == 'image' else '视频'}生成任务 #{item.get('id')}"
    item["display_prompt"] = prompt or f"生成任务 #{item.get('id')}"
    return item


class MultimodalConfigRepository:
    @staticmethod
    def get_config() -> dict:
        image_model = ModelRepository.get_for_capability("image")
        video_model = ModelRepository.get_for_capability("video")
        model = image_model or video_model
        if model:
            provider_text = f"{model.get('provider', '')} {model.get('model_name', '')}".lower()
            return {
                "enabled": bool(image_model or video_model),
                "provider": "minimax" if "minimax" in provider_text else "openai_compatible",
                "api_key_env": model.get("api_key_env") or "",
                "api_secret_env": "",
                "base_url": (
                    (image_model or {}).get("image_base_url")
                    or (video_model or {}).get("video_base_url")
                    or model.get("base_url")
                    or ""
                ),
                "default_image_size": "1024x1024",
                "default_video_duration": 6,
                "image_model": (image_model or {}).get("image_model") or "",
                "video_model": (video_model or {}).get("video_model") or "",
                "video_enabled": bool(video_model),
                "model_id": model.get("id"),
            }
        with connection_scope() as connection:
            row = connection.execute("SELECT * FROM multimodal_config WHERE id=1").fetchone()
        if not row:
            return {
                "enabled": False,
                "provider": "openai_compatible",
                "api_key_env": "",
                "api_secret_env": "",
                "base_url": "",
                "default_image_size": "1024x1024",
                "default_video_duration": 5,
                "image_model": "",
                "video_enabled": False,
            }
        config = dict(row)
        config["enabled"] = bool(config["enabled"])
        config["video_enabled"] = bool(config.get("video_enabled"))
        return config

    @staticmethod
    def update_config(data: dict) -> dict:
        current = MultimodalConfigRepository.get_config()
        provider = str(data.get("provider", current["provider"])).strip().lower()
        if provider not in {"minimax", "openai", "openai_compatible"}:
            raise ValueError("多模态服务仅支持 MiniMax 或 OpenAI API 兼容生图服务")
        enabled_raw = data.get("enabled", current["enabled"])
        enabled = (
            enabled_raw.strip().lower() in {"1", "true", "yes", "on"}
            if isinstance(enabled_raw, str)
            else bool(enabled_raw)
        )
        video_raw = data.get("video_enabled", current.get("video_enabled", False))
        video_enabled = (
            video_raw.strip().lower() in {"1", "true", "yes", "on"}
            if isinstance(video_raw, str)
            else bool(video_raw)
        )
        api_key_env = str(data.get("api_key_env", current["api_key_env"])).strip()
        api_secret_env = str(data.get("api_secret_env", current["api_secret_env"])).strip()
        for name in (api_key_env, api_secret_env):
            if name and not ENV_NAME.fullmatch(name):
                raise ValueError("密钥配置只能填写大写环境变量名称")
        base_url = str(data.get("base_url", current["base_url"])).strip()
        if base_url:
            parsed = urlsplit(base_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("多模态服务地址必须是无凭据的 HTTPS URL")
        image_size = str(
            data.get("default_image_size", current["default_image_size"])
        ).strip()
        if image_size not in IMAGE_SIZES:
            raise ValueError("默认图片尺寸不受支持")
        duration = int(
            data.get("default_video_duration", current["default_video_duration"])
        )
        if not 1 <= duration <= 60:
            raise ValueError("默认视频时长需为 1—60 秒")
        image_model = str(data.get("image_model", current.get("image_model", ""))).strip()
        if len(image_model) > 100:
            raise ValueError("图片模型名称过长")
        with connection_scope() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO multimodal_config
                   (id,enabled,provider,api_key_env,api_secret_env,base_url,
                    default_image_size,default_video_duration,image_model,video_enabled,updated_at)
                   VALUES (1,?,?,?,?,?,?,?,?,?,strftime('%s','now'))""",
                (
                    int(enabled),
                    "minimax" if provider == "minimax" else "openai_compatible",
                    api_key_env,
                    api_secret_env,
                    base_url,
                    image_size,
                    duration,
                    image_model,
                    int(video_enabled),
                ),
            )
            connection.commit()
        return MultimodalConfigRepository.get_config()


class MultimodalTaskRepository:
    @staticmethod
    def create(
        task_type: str,
        prompt: str,
        parameters: dict,
        user_id: int | None = None,
    ) -> dict:
        if task_type not in {"image", "video"}:
            raise ValueError("多模态任务类型不受支持")
        task_id = str(uuid.uuid4())
        with connection_scope() as connection:
            connection.execute(
                """INSERT INTO multimodal_tasks
                   (task_id,user_id,task_type,prompt,parameters,status)
                   VALUES (?,?,?,?,?,'pending')""",
                (
                    task_id,
                    user_id,
                    task_type,
                    prompt[:4000],
                    json.dumps(parameters, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            connection.commit()
        return MultimodalTaskRepository.get(task_id)

    @staticmethod
    def get(task_id: str, user_id: int | None = None) -> dict | None:
        clauses = ["task_id=?"]
        params: list[object] = [task_id]
        if user_id is not None:
            clauses.append("user_id=?")
            params.append(user_id)
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT * FROM multimodal_tasks WHERE " + " AND ".join(clauses), params
            ).fetchone()
        return _task(row)

    @staticmethod
    def mark_running(task_id: str, provider: str) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                """UPDATE multimodal_tasks SET status='running',provider=?,
                   error_message='',updated_at=CURRENT_TIMESTAMP
                   WHERE task_id=? AND status='pending'""",
                (provider, task_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def complete(
        task_id: str,
        *,
        resource_url: str,
        result: dict,
        provider_task_id: str = "",
        latency_ms: int = 0,
    ) -> None:
        with connection_scope() as connection:
            connection.execute(
                """UPDATE multimodal_tasks SET status='completed',resource_url=?,result=?,
                   provider_task_id=?,latency_ms=?,error_message='',
                   completed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                   WHERE task_id=?""",
                (
                    resource_url[:2000],
                    json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                    provider_task_id[:200],
                    max(0, int(latency_ms)),
                    task_id,
                ),
            )
            connection.commit()

    @staticmethod
    def fail(task_id: str, message: str, latency_ms: int = 0) -> None:
        with connection_scope() as connection:
            connection.execute(
                """UPDATE multimodal_tasks SET status='failed',error_message=?,latency_ms=?,
                   completed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE task_id=?""",
                (message.strip()[:500], max(0, int(latency_ms)), task_id),
            )
            connection.commit()

    @staticmethod
    def list(task_type: str = "", limit: int = 50) -> list[dict]:
        clauses: list[str] = []
        params: list[object] = []
        if task_type in {"image", "video"}:
            clauses.append("task_type=?")
            params.append(task_type)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with connection_scope() as connection:
            rows = connection.execute(
                "SELECT * FROM multimodal_tasks" + where + " ORDER BY id DESC LIMIT ?",
                (*params, min(100, max(1, int(limit)))),
            ).fetchall()
        return [_task(row) for row in rows]

    @staticmethod
    def delete(task_id: str) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                "DELETE FROM multimodal_tasks WHERE task_id=?", (task_id,)
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def stats() -> dict:
        with connection_scope() as connection:
            row = connection.execute(
                """SELECT COUNT(*) total_calls,
                   SUM(status='completed') success_calls,
                   SUM(task_type='image') image_calls,
                   SUM(task_type='video') video_calls
                   FROM multimodal_tasks"""
            ).fetchone()
        return {key: int(row[key] or 0) for key in row.keys()}


# Compatibility name used by the existing controller imports.
MultimodalCallRepository = MultimodalTaskRepository
