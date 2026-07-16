"""OpenAI API 兼容模型配置、默认模型与 SSE 对话。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from urllib.parse import urlparse

from tornado.iostream import StreamClosedError

from app.controllers.base import AdminBaseHandler, AdminJsonHandler
from app.models.model_engine import ModelRepository
from app.services.llm import LLMService

LOGGER = logging.getLogger("model")


MODEL_TYPES = (
    ("text", "文本"),
    ("image", "图像"),
    ("audio", "音频"),
    ("video", "视频"),
    ("multimodal", "多模态"),
    ("embedding", "嵌入"),
)
MODEL_TYPE_CODES = {item[0] for item in MODEL_TYPES}
ENV_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]{1,127}$")


def _page(handler: AdminBaseHandler) -> int:
    try:
        return max(1, int(handler.get_query_argument("page", "1")))
    except ValueError:
        return 1


def _float(handler: AdminBaseHandler, name: str, default: float) -> float:
    try:
        return float(handler.get_body_argument(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} 必须是数字") from exc


def _integer(handler: AdminBaseHandler, name: str, default: int) -> int:
    try:
        return int(handler.get_body_argument(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc


def _operation_message(result, success: str) -> tuple[str, str]:
    if isinstance(result, tuple):
        ok, message = result
        return str(message), "success" if ok else "error"
    return (success, "success") if result else ("操作失败，请检查配置是否重复", "error")


class AdminModelsHandler(AdminBaseHandler):
    required_feature = "model_engine"

    def get(self):
        keyword = self.get_query_argument("q", "").strip()
        selected_type = self.get_query_argument("type", "").strip()
        status = self.get_query_argument("status", "").strip()
        if selected_type not in MODEL_TYPE_CODES:
            selected_type = ""
        if status not in {"", "enabled", "disabled"}:
            status = ""
        page = _page(self)
        models, total = ModelRepository.list(
            keyword=keyword,
            model_type=selected_type,
            status=status,
            page=page,
            page_size=6,
        )
        type_labels = dict(MODEL_TYPES)
        for model in models:
            model["type_label"] = type_labels.get(model["model_type"], model["model_type"])
            model["total_calls"] = int(model.get("usage_count", 0))
            model.setdefault("last_used_at", "")
        self.render_admin(
            "admin/models.html",
            title="模型引擎 · 瞭望与问数系统",
            active_menu="model_engine",
            models=models,
            model_types=MODEL_TYPES,
            keyword=keyword,
            selected_type=selected_type,
            selected_status=status,
            page=page,
            pages=max(1, (total + 5) // 6),
            total=total,
            can_write=True,
        )

    def post(self):
        action = self.get_body_argument("action", "")
        try:
            if action in {"create", "update"}:
                model_id = _integer(self, "model_id", 0) if action == "update" else None
                name = self.get_body_argument("name", "").strip()
                provider = self.get_body_argument("provider", "OpenAI Compatible").strip()
                model_name = self.get_body_argument("model_name", "").strip()
                model_type = self.get_body_argument("model_type", "text").strip()
                base_url = self.get_body_argument("base_url", "").strip().rstrip("/")
                api_key_env = self.get_body_argument("api_key_env", "OPENAI_API_KEY").strip()
                system_prompt = self.get_body_argument("system_prompt", "").strip()[:4000]
                temperature = _float(self, "temperature", 0.7)
                top_p = _float(self, "top_p", 1.0)
                max_tokens = _integer(self, "max_tokens", 1024)
                context_messages = _integer(self, "context_messages", 8)
                enabled = self.get_body_argument("enabled", "1") == "1"
                if not 2 <= len(name) <= 60 or not 1 <= len(model_name) <= 120:
                    raise ValueError("显示名称或模型标识长度不正确")
                if not 2 <= len(provider) <= 60 or model_type not in MODEL_TYPE_CODES:
                    raise ValueError("服务商或模型分类无效")
                parsed = urlparse(base_url)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    raise ValueError("Base URL 必须是有效的 HTTP/HTTPS 地址")
                if not ENV_PATTERN.fullmatch(api_key_env):
                    raise ValueError("API Key 环境变量名称格式不正确")
                if not 0 <= temperature <= 2 or not 0 <= top_p <= 1:
                    raise ValueError("temperature 需为 0—2，top_p 需为 0—1")
                if not 1 <= max_tokens <= 128000 or not 1 <= context_messages <= 100:
                    raise ValueError("最大 Token 或上下文条数超出范围")
                values = dict(
                    name=name,
                    provider=provider,
                    model_name=model_name,
                    model_type=model_type,
                    base_url=base_url,
                    api_key_env=api_key_env,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                    context_messages=context_messages,
                    enabled=enabled,
                )
                if model_id:
                    result = ModelRepository.update(model_id=model_id, **values)
                    message, level = _operation_message(result, "模型配置已更新")
                else:
                    result = ModelRepository.create(
                        created_by=self.current_user["id"], **values
                    )
                    message, level = _operation_message(result, "模型创建成功")
                return self.redirect_with_message("/admin/models", message, level)

            model_id = _integer(self, "model_id", 0)
            if action == "delete":
                result = ModelRepository.delete(model_id)
                message, level = _operation_message(result, "模型已删除")
            elif action == "toggle":
                result = ModelRepository.toggle(model_id)
                message, level = _operation_message(result, "模型启用状态已更新")
            elif action == "set_default":
                result = ModelRepository.set_default(model_id)
                message, level = _operation_message(result, "默认模型已更新")
            else:
                raise ValueError("未知操作")
            self.redirect_with_message("/admin/models", message, level)
        except ValueError as exc:
            self.redirect_with_message("/admin/models", str(exc), "error")


class AdminModelChatHandler(AdminJsonHandler):
    required_feature = "model_engine"

    async def _event(self, name: str, payload: dict) -> None:
        self.write(
            f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        )
        await self.flush()

    async def post(self):
        payload = self.json_body()
        prompt = str(payload.get("prompt", payload.get("message", ""))).strip()
        if not 1 <= len(prompt) <= 8000:
            return self.write_json({"ok": False, "message": "请输入 1—8000 个字符的问题"}, 400)
        try:
            model_id = int(payload.get("model_id") or 0)
        except (TypeError, ValueError):
            model_id = 0
        model = ModelRepository.get(model_id) if model_id else ModelRepository.get_default()
        if not model or not model.get("enabled"):
            return self.write_json({"ok": False, "message": "请选择一个已启用的模型"}, 404)
        if model.get("model_type") not in {"text", "multimodal"}:
            return self.write_json({"ok": False, "message": "当前模型类型不支持文本对话"}, 400)

        self.set_header("Content-Type", "text/event-stream; charset=UTF-8")
        self.set_header("Cache-Control", "no-cache, no-transform")
        self.set_header("X-Accel-Buffering", "no")
        try:
            await self._event("meta", {"status": "正在连接模型服务", "request_id": self.request_id})
            result = await LLMService.complete(model, prompt)
            text = str(result.get("text", ""))
            for offset in range(0, len(text), 12):
                await self._event("delta", {"delta": text[offset : offset + 12]})
                await asyncio.sleep(0)
            usage = {
                "prompt_tokens": int(result.get("prompt_tokens", 0)),
                "completion_tokens": int(result.get("completion_tokens", 0)),
                "total_tokens": int(result.get("total_tokens", 0)),
                "latency_ms": int(result.get("latency_ms", 0)),
            }
            ModelRepository.record_usage(
                model_id=model["id"],
                user_id=self.current_user["id"],
                success=True,
                **usage,
            )
            await self._event("done", {"status": "已完成", "ok": True, "usage": usage})
        except StreamClosedError:
            return
        except Exception as exc:
            LOGGER.exception("admin model stream failed", extra={"user_id": self.current_user["id"], "request_id": self.request_id, "event": "admin_model_stream_failed"})
            message = str(exc)[:300] or "模型服务调用失败"
            ModelRepository.record_usage(
                model_id=model["id"],
                user_id=self.current_user["id"],
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                latency_ms=0,
                success=False,
                error_message=message,
            )
            try:
                await self._event("error", {"error": message})
            except StreamClosedError:
                return
