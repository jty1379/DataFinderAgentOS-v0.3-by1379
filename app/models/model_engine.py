"""OpenAI 兼容模型配置与用量 Repository。"""

from __future__ import annotations

import re
import sqlite3
from urllib.parse import urlsplit

from app.models.db import connection_scope
from config.settings import SETTINGS


MODEL_TYPES = ("text", "image", "audio", "video", "multimodal", "embedding")
ENV_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]{1,127}$")


def _bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _model(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["is_default"] = bool(item["is_default"])
    item["api_key_configured"] = bool(
        item.get("api_key_env") and SETTINGS.secret_from_env(item["api_key_env"])
    )
    return item


class ModelRepository:
    SELECT = """
        SELECT m.*,
               COUNT(mu.id) AS usage_count,
               COALESCE(SUM(mu.prompt_tokens), 0) AS prompt_tokens,
               COALESCE(SUM(mu.completion_tokens), 0) AS completion_tokens,
               COALESCE(SUM(mu.total_tokens), 0) AS total_tokens,
               COALESCE(AVG(CASE WHEN mu.success = 1 THEN mu.latency_ms END), 0)
                   AS avg_latency_ms,
               MAX(mu.created_at) AS last_used_at
        FROM model_configs m
        LEFT JOIN model_usage mu ON mu.model_id = m.id
    """

    @staticmethod
    def list(
        keyword: str = "",
        model_type: str = "",
        status: str = "",
        page: int = 1,
        page_size: int = 6,
    ) -> tuple[list[dict], int]:
        page = max(1, int(page or 1))
        page_size = min(100, max(1, int(page_size or 6)))
        offset = (page - 1) * page_size
        keyword = keyword.strip()
        pattern = f"%{keyword}%"
        clauses: list[str] = []
        params: list[object] = []
        if keyword:
            clauses.append("(m.name LIKE ? OR m.model_name LIKE ? OR m.provider LIKE ?)")
            params.extend([pattern, pattern, pattern])
        if model_type in MODEL_TYPES:
            clauses.append("m.model_type = ?")
            params.append(model_type)
        normalized_status = status.strip().lower()
        if normalized_status in {"1", "enabled", "true"}:
            clauses.append("m.enabled = 1")
        elif normalized_status in {"0", "disabled", "false"}:
            clauses.append("m.enabled = 0")
        where = " AND ".join(clauses)
        with connection_scope() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM model_configs m WHERE " + where,
                    params,
                ).fetchone()["count"]
            )
            rows = connection.execute(
                ModelRepository.SELECT
                + " WHERE "
                + where
                + " GROUP BY m.id ORDER BY m.is_default DESC, m.id DESC LIMIT ? OFFSET ?",
                (*params, page_size, offset),
            ).fetchall()
        return [_model(row) for row in rows], total

    @staticmethod
    def get(model_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                ModelRepository.SELECT + " WHERE m.id = ? GROUP BY m.id", (model_id,)
            ).fetchone()
        return _model(row)

    @staticmethod
    def _normalized(values: dict, current: dict | None = None) -> dict:
        current = current or {}
        model_type = str(values.get("model_type", current.get("model_type", "text"))).strip()
        if model_type not in MODEL_TYPES:
            raise ValueError("模型分类无效")
        name = str(values.get("name", current.get("name", ""))).strip()
        model_name = str(values.get("model_name", current.get("model_name", ""))).strip()
        provider = str(
            values.get("provider", current.get("provider", "OpenAI Compatible"))
        ).strip()
        if not 2 <= len(name) <= 60 or not 1 <= len(model_name) <= 120:
            raise ValueError("模型名称或调用标识格式不正确")
        if not 2 <= len(provider) <= 60:
            raise ValueError("服务商名称需为 2—60 个字符")
        base_url = str(values.get("base_url", current.get("base_url", ""))).strip().rstrip("/")
        parsed = urlsplit(base_url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("接口地址仅支持完整的 http/https URL")
        if parsed.username or parsed.password:
            raise ValueError("接口地址不允许嵌入凭据")
        api_key_env = str(
            values.get("api_key_env", current.get("api_key_env", "OPENAI_API_KEY"))
        ).strip()
        if api_key_env and not ENV_PATTERN.fullmatch(api_key_env):
            raise ValueError("API Key 环境变量名格式不正确")
        temperature = float(values.get("temperature", current.get("temperature", 0.7)))
        top_p = float(values.get("top_p", current.get("top_p", 1.0)))
        max_tokens = int(values.get("max_tokens", current.get("max_tokens", 2048)))
        context_messages = int(
            values.get("context_messages", current.get("context_messages", 10))
        )
        if not 0 <= temperature <= 2 or not 0 <= top_p <= 1:
            raise ValueError("温度或 top_p 超出取值范围")
        if not 1 <= max_tokens <= 131072 or not 1 <= context_messages <= 100:
            raise ValueError("最大 token 或上下文条数超出取值范围")
        return {
            "name": name,
            "model_name": model_name,
            "provider": provider,
            "model_type": model_type,
            "base_url": base_url,
            "api_key_env": api_key_env,
            "system_prompt": str(
                values.get("system_prompt", current.get("system_prompt", ""))
            ).strip()[:10000],
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "context_messages": context_messages,
            "enabled": int(_bool(values.get("enabled", current.get("enabled", True)))),
            "is_default": int(
                _bool(values.get("is_default", current.get("is_default", False)))
            ),
            "created_by": values.get("created_by", current.get("created_by")),
        }

    @staticmethod
    def _ensure_default(connection) -> None:
        existing = connection.execute(
            "SELECT id FROM model_configs WHERE is_default = 1 AND enabled = 1 LIMIT 1"
        ).fetchone()
        if existing:
            return
        connection.execute("UPDATE model_configs SET is_default = 0 WHERE is_default = 1")
        replacement = connection.execute(
            "SELECT id FROM model_configs WHERE enabled = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        if replacement:
            connection.execute(
                "UPDATE model_configs SET is_default = 1 WHERE id = ?", (replacement["id"],)
            )

    @staticmethod
    def create(**values) -> int | None:
        data = ModelRepository._normalized(values)
        if not data["enabled"]:
            data["is_default"] = 0
        try:
            with connection_scope() as connection:
                if data["is_default"]:
                    connection.execute("UPDATE model_configs SET is_default = 0")
                cursor = connection.execute(
                    """
                    INSERT INTO model_configs
                        (name, model_name, provider, model_type, base_url, api_key_env,
                         system_prompt, temperature, top_p, max_tokens, context_messages,
                         enabled, is_default, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    tuple(data[key] for key in (
                        "name", "model_name", "provider", "model_type", "base_url",
                        "api_key_env", "system_prompt", "temperature", "top_p",
                        "max_tokens", "context_messages", "enabled", "is_default", "created_by",
                    )),
                )
                ModelRepository._ensure_default(connection)
                connection.commit()
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None

    @staticmethod
    def update(model_id: int, **values) -> bool:
        current = ModelRepository.get(model_id)
        if not current:
            return False
        data = ModelRepository._normalized(values, current)
        if not data["enabled"]:
            data["is_default"] = 0
        try:
            with connection_scope() as connection:
                if data["is_default"]:
                    connection.execute("UPDATE model_configs SET is_default = 0")
                cursor = connection.execute(
                    """
                    UPDATE model_configs
                    SET name = ?, model_name = ?, provider = ?, model_type = ?, base_url = ?,
                        api_key_env = ?, system_prompt = ?, temperature = ?, top_p = ?,
                        max_tokens = ?, context_messages = ?, enabled = ?, is_default = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        *(data[key] for key in (
                            "name", "model_name", "provider", "model_type", "base_url",
                            "api_key_env", "system_prompt", "temperature", "top_p",
                            "max_tokens", "context_messages", "enabled", "is_default",
                        )),
                        model_id,
                    ),
                )
                ModelRepository._ensure_default(connection)
                connection.commit()
            return cursor.rowcount == 1
        except sqlite3.IntegrityError:
            return False

    @staticmethod
    def delete(model_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute("DELETE FROM model_configs WHERE id = ?", (model_id,))
            ModelRepository._ensure_default(connection)
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def toggle(model_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                UPDATE model_configs
                SET enabled = CASE enabled WHEN 1 THEN 0 ELSE 1 END,
                    is_default = CASE WHEN enabled = 1 THEN 0 ELSE is_default END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (model_id,),
            )
            ModelRepository._ensure_default(connection)
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def set_default(model_id: int) -> bool:
        with connection_scope() as connection:
            target = connection.execute(
                "SELECT id FROM model_configs WHERE id = ? AND enabled = 1", (model_id,)
            ).fetchone()
            if target is None:
                return False
            connection.execute("UPDATE model_configs SET is_default = 0")
            cursor = connection.execute(
                """
                UPDATE model_configs SET is_default = 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND enabled = 1
                """,
                (model_id,),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def get_default():
        with connection_scope() as connection:
            row = connection.execute(
                ModelRepository.SELECT
                + " WHERE m.is_default = 1 AND m.enabled = 1 GROUP BY m.id LIMIT 1"
            ).fetchone()
        return _model(row)

    @staticmethod
    def record_usage(
        model_id: int,
        user_id: int | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        latency_ms: int = 0,
        success: bool = True,
        error_message: str = "",
    ) -> int | None:
        prompt_tokens = max(0, int(prompt_tokens or 0))
        completion_tokens = max(0, int(completion_tokens or 0))
        total_tokens = max(
            0, int(total_tokens or (prompt_tokens + completion_tokens))
        )
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO model_usage
                        (model_id, user_id, prompt_tokens, completion_tokens,
                         total_tokens, latency_ms, success, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        model_id,
                        user_id,
                        prompt_tokens,
                        completion_tokens,
                        total_tokens,
                        max(0, int(latency_ms or 0)),
                        int(bool(success)),
                        error_message.strip()[:500],
                    ),
                )
                connection.commit()
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None

    @staticmethod
    def usage_summary(model_id: int) -> dict:
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS usage_count,
                       COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                       COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                       COALESCE(SUM(total_tokens), 0) AS total_tokens,
                       COALESCE(AVG(CASE WHEN success = 1 THEN latency_ms END), 0)
                           AS avg_latency_ms,
                       MAX(created_at) AS last_used_at
                FROM model_usage WHERE model_id = ?
                """,
                (model_id,),
            ).fetchone()
        return dict(row)

    @staticmethod
    def list_usage_logs(
        model_id: int,
        success_only: bool = False,
        failure_only: bool = False,
        limit: int = 20,
    ) -> list[dict]:
        """获取模型的调用日志明细。"""
        limit = min(100, max(1, int(limit or 20)))
        clauses = ["model_id = ?"]
        params: list[object] = [model_id]
        if success_only:
            clauses.append("success = 1")
        elif failure_only:
            clauses.append("success = 0")
        where = " AND ".join(clauses)
        with connection_scope() as connection:
            rows = connection.execute(
                f"""SELECT mu.*, u.username AS user_name
                    FROM model_usage mu
                    LEFT JOIN users u ON u.id = mu.user_id
                    WHERE {where}
                    ORDER BY mu.created_at DESC
                    LIMIT ?""",
                (*params, limit),
            ).fetchall()
        return [dict(row) for row in rows]
