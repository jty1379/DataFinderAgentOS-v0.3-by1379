"""User chat orchestration shared by JSON and SSE endpoints."""

from __future__ import annotations

import json
import logging
import time

from app.models.conversation import ConversationRepository
from app.models.digital_employee import DigitalEmployeeRepository
from app.models.model_engine import ModelRepository
from app.services.digital_employee import DigitalEmployeeError, DigitalEmployeeService
from app.services.llm import LLMService
from app.services.opinion import OpinionSecurityService
from app.services.query_intent import QueryIntentService, UnsafeQueryError
from app.services.system_settings import SystemSettingsService

LOGGER = logging.getLogger("model")


class UserChatError(ValueError):
    def __init__(self, message: str, status: int = 400, conversation_id: int | None = None):
        super().__init__(message)
        self.status = status
        self.conversation_id = conversation_id


def _integer(value) -> int | None:
    try:
        number = int(value or 0)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


class UserChatService:
    @staticmethod
    async def process(payload: dict, user_id: int, on_delta=None) -> dict:
        started = time.monotonic()
        prompt = str(payload.get("message", "")).strip()
        if not 1 <= len(prompt) <= 8000:
            raise UserChatError("请输入 1—8000 个字符的问题")

        conversation_id = _integer(payload.get("conversation_id"))
        model_id = _integer(payload.get("model_id"))
        employee_id = _integer(payload.get("employee_id"))
        conversation = None
        if conversation_id:
            conversation = ConversationRepository.get_for_user(conversation_id, user_id)
            if not conversation:
                raise UserChatError("会话不存在或不属于当前用户", 404)

        employee = DigitalEmployeeRepository.get(employee_id) if employee_id else None
        if employee_id and (
            not employee or not employee.get("enabled")
            or employee.get("code") == "collection_specialist"
        ):
            raise UserChatError("所选数字员工不存在或不可用于用户问数")

        model = ModelRepository.get(model_id) if model_id else SystemSettingsService.get_default_model()
        if model and (not model.get("enabled") or model.get("model_type") not in {"text", "multimodal"}):
            raise UserChatError("所选模型当前不可用于文本对话")
        selected_model_id = model["id"] if model else None

        if not conversation_id:
            conversation_id = ConversationRepository.create(
                user_id=user_id,
                title=ConversationRepository.title_from_prompt(prompt),
                model_id=selected_model_id,
                employee_id=employee_id,
            )
        else:
            ConversationRepository.update_context(
                conversation_id, user_id, selected_model_id, employee_id
            )
        user_message_id = ConversationRepository.add_message(
            conversation_id, "user", prompt, "text",
            {"model_id": selected_model_id, "employee_id": employee_id},
        )
        user_security = OpinionSecurityService.analyze_and_record(
            "chat", user_message_id, prompt, user_id,
            {"conversation_id": conversation_id, "role": "user"},
        )
        ConversationRepository.update_message_security(user_message_id, user_security)

        try:
            result = await UserChatService._answer(
                prompt, conversation_id, user_id, employee, model, on_delta
            )
            metadata = dict(result["metadata"])
            usage = dict(metadata.get("usage") or {})
            usage.setdefault("prompt_tokens", 0)
            usage.setdefault("completion_tokens", 0)
            usage.setdefault("total_tokens", 0)
            usage["latency_ms"] = max(
                int(usage.get("latency_ms") or 0),
                int((time.monotonic() - started) * 1000),
            )
            metadata["usage"] = usage
            metadata["elapsed_seconds"] = round(usage["latency_ms"] / 1000, 2)
            assistant_message_id = ConversationRepository.add_message(
                conversation_id, "assistant", result["answer"], result["content_type"], metadata
            )
            assistant_security = OpinionSecurityService.analyze_and_record(
                "chat", assistant_message_id, result["answer"], user_id,
                {
                    "conversation_id": conversation_id,
                    "role": "assistant",
                    "employee_id": employee["id"] if employee else None,
                },
            )
            ConversationRepository.update_message_security(assistant_message_id, assistant_security)
            return {
                "ok": True,
                "conversation": ConversationRepository.get_for_user(conversation_id, user_id),
                "message": {
                    "role": "assistant",
                    "content": result["answer"],
                    "content_type": result["content_type"],
                    "metadata": metadata,
                },
            }
        except Exception as exc:
            LOGGER.exception("user chat processing failed", extra={"user_id": user_id, "event": "user_chat_failed"})
            message = str(exc)[:500] or "问数服务调用失败，请稍后重试"
            if model and not employee:
                ModelRepository.record_usage(
                    model_id=model["id"], user_id=user_id, success=False,
                    error_message=message,
                )
            metadata = {
                "recoverable": True,
                "usage": {"total_tokens": 0, "latency_ms": int((time.monotonic() - started) * 1000)},
                "elapsed_seconds": round(time.monotonic() - started, 2),
            }
            assistant_message_id = ConversationRepository.add_message(
                conversation_id, "assistant", message, "error", metadata
            )
            assistant_security = OpinionSecurityService.analyze_and_record(
                "chat", assistant_message_id, message, user_id,
                {"conversation_id": conversation_id, "role": "assistant", "error": True},
            )
            ConversationRepository.update_message_security(assistant_message_id, assistant_security)
            status = 400 if isinstance(
                exc, (ValueError, DigitalEmployeeError, UnsafeQueryError)
            ) else 502
            raise UserChatError(message, status, conversation_id) from exc

    @staticmethod
    async def _answer(prompt, conversation_id, user_id, employee, model, on_delta=None) -> dict:
        QueryIntentService.validate(prompt)
        if employee:
            employee_prompt = prompt
            for prefix in (f"@{employee['mention']}", f"/{employee['mention']}"):
                if employee_prompt.startswith(prefix):
                    employee_prompt = employee_prompt[len(prefix):].strip()
                    break
            if not employee_prompt:
                raise DigitalEmployeeError(f"请在 @{employee['mention']} 后输入具体问题")
            result = await DigitalEmployeeService.preview(employee["id"], employee_prompt, user_id)
            answer = (
                str(result.get("text", "")) if result.get("mode") == "text"
                else json.dumps(result.get("data", {}), ensure_ascii=False)
            )
            content_type = "text" if result.get("mode") == "text" else (
                "card" if result.get("mode") == "card" else "json"
            )
            return {"answer": answer, "content_type": content_type, "metadata": result}

        routed = QueryIntentService.analyze(prompt)
        if routed:
            return {
                "answer": json.dumps(routed["data"], ensure_ascii=False),
                "content_type": "card",
                "metadata": routed,
            }
        if not model:
            raise ValueError("后台尚未配置可用模型；可先询问数据仓库统计，或使用 @天气 查询公开天气数据")
        history = ConversationRepository.messages(conversation_id, user_id)[-10:-1]
        context = "\n".join(
            ("用户" if item["role"] == "user" else "助手") + "：" + item["content"]
            for item in history if item["content_type"] == "text"
        )
        full_prompt = (
            f"以下是当前会话上下文：\n{context}\n\n用户最新问题：{prompt}"
            if context else prompt
        )
        result = await (
            LLMService.complete_stream(model, full_prompt, on_delta)
            if on_delta else LLMService.complete(model, full_prompt)
        )
        ModelRepository.record_usage(
            model_id=model["id"], user_id=user_id, success=True,
            prompt_tokens=result.get("prompt_tokens", 0),
            completion_tokens=result.get("completion_tokens", 0),
            total_tokens=result.get("total_tokens", 0),
            latency_ms=result.get("latency_ms", 0),
        )
        return {
            "answer": str(result.get("text", "")),
            "content_type": "text",
            "metadata": {
                "mode": "text", "model": model["name"],
                "usage": {key: result.get(key, 0) for key in (
                    "prompt_tokens", "completion_tokens", "total_tokens", "latency_ms"
                )},
            },
        }
