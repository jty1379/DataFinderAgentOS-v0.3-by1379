"""多模态服务数据模型。"""

from __future__ import annotations

import json
import time
from typing import Any

from app.models.db import connection_scope


class MultimodalConfigRepository:
    TABLE_NAME = "multimodal_config"

    @classmethod
    def get_config(cls) -> dict:
        with connection_scope() as connection:
            row = connection.execute(f"SELECT * FROM {cls.TABLE_NAME} LIMIT 1").fetchone()
            if row:
                return {
                    "enabled": row["enabled"],
                    "provider": row["provider"],
                    "api_key_env": row["api_key_env"],
                    "api_secret_env": row["api_secret_env"],
                    "base_url": row["base_url"],
                    "default_image_size": row["default_image_size"],
                    "default_video_duration": row["default_video_duration"],
                }
        return cls._default_config()

    @classmethod
    def _default_config(cls) -> dict:
        return {
            "enabled": True,
            "provider": "volcengine",
            "api_key_env": "",
            "api_secret_env": "",
            "base_url": "",
            "default_image_size": "1024x1024",
            "default_video_duration": 5,
        }

    @classmethod
    def update_config(cls, data: dict) -> dict:
        config = cls.get_config()
        config.update(data)
        with connection_scope() as connection:
            connection.execute(
                f"""INSERT OR REPLACE INTO {cls.TABLE_NAME} (id, enabled, provider, api_key_env, api_secret_env, base_url, default_image_size, default_video_duration, updated_at)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (config["enabled"], config["provider"], config["api_key_env"], config["api_secret_env"],
                 config["base_url"], config["default_image_size"], config["default_video_duration"], time.time()),
            )
        return config


class MultimodalCallRepository:
    TABLE_NAME = "multimodal_calls"

    @classmethod
    def create_call(cls, task_type: str, task_id: str, prompt: str) -> int:
        with connection_scope() as connection:
            cursor = connection.execute(
                f"""INSERT INTO {cls.TABLE_NAME} (task_type, task_id, prompt, status, result, created_at, updated_at)
                   VALUES (?, ?, ?, 'running', '', ?, ?)""",
                (task_type, task_id, prompt, time.time(), time.time()),
            )
            return cursor.lastrowid

    @classmethod
    def update_call(cls, task_id: str, status: str, result: str = "") -> None:
        with connection_scope() as connection:
            connection.execute(
                f"""UPDATE {cls.TABLE_NAME} SET status = ?, result = ?, updated_at = ? WHERE task_id = ?""",
                (status, result, time.time(), task_id),
            )

    @classmethod
    def get_stats(cls) -> dict:
        with connection_scope() as connection:
            total = connection.execute(f"SELECT COUNT(*) as cnt FROM {cls.TABLE_NAME}").fetchone()["cnt"]
            success = connection.execute(f"SELECT COUNT(*) as cnt FROM {cls.TABLE_NAME} WHERE status = 'completed'").fetchone()["cnt"]
            image = connection.execute(f"SELECT COUNT(*) as cnt FROM {cls.TABLE_NAME} WHERE task_type = 'image'").fetchone()["cnt"]
            video = connection.execute(f"SELECT COUNT(*) as cnt FROM {cls.TABLE_NAME} WHERE task_type = 'video'").fetchone()["cnt"]
            return {
                "total_calls": total,
                "success_calls": success,
                "image_calls": image,
                "video_calls": video,
            }

    @classmethod
    def list_calls(cls, task_type: str = None, limit: int = 20) -> list:
        with connection_scope() as connection:
            query = f"SELECT * FROM {cls.TABLE_NAME}"
            params = []
            if task_type:
                query += " WHERE task_type = ?"
                params.append(task_type)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = connection.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    @classmethod
    def delete_call(cls, task_id: str) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                f"DELETE FROM {cls.TABLE_NAME} WHERE task_id = ?", (task_id,)
            )
            return cursor.rowcount == 1