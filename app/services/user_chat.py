"""User chat orchestration shared by JSON and SSE endpoints."""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path

from app.core.prompt_safety import (
    PromptInjectionError,
    add_untrusted_policy,
    validate_untrusted_content,
    wrap_untrusted_content,
)
from app.models.conversation import ConversationRepository
from app.models.digital_employee import DigitalEmployeeRepository
from app.models.model_engine import ModelRepository
from app.services.digital_employee import DigitalEmployeeError, DigitalEmployeeService
from app.services.llm import LLMService
from app.services.opinion import OpinionSecurityService
from app.services.query_intent import QueryIntentService, UnsafeQueryError
from app.services.system_settings import SystemSettingsService
from config.settings import BASE_DIR

LOGGER = logging.getLogger("model")

UPLOAD_ROOT = BASE_DIR / "data" / "uploads"
IMAGE_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}
DOC_EXT = {"pdf", "txt", "md", "markdown"}
MAX_DOCS = 4
MAX_DOC_CHARS = 12000
MAX_DOC_BYTES = 8 * 1024 * 1024
PROMPT_LIMIT = 20000


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


def _image_urls(raw) -> list[str]:
    """仅保留最多 4 个非空字符串 URL。"""
    if not isinstance(raw, list):
        return []
    urls = [str(item).strip() for item in raw if str(item or "").strip()]
    return urls[:4]


def _resolve_upload_path(url: str, user_id: int, allowed_ext) -> tuple[Path, str]:
    """校验用户上传附件 URL 并返回本地路径与扩展名（防目录逃逸、限当前用户）。"""
    prefix = f"/api/uploads/{user_id}/"
    if not url.startswith(prefix):
        raise UserChatError("附件无效或不属于当前用户")
    filename = url[len(prefix):]
    if "/" in filename or "\\" in filename or ".." in filename:
        raise UserChatError("附件无效")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in allowed_ext:
        raise UserChatError("附件格式不受支持")
    root = UPLOAD_ROOT.resolve()
    path = (UPLOAD_ROOT / str(user_id) / filename).resolve()
    if root not in path.parents or not path.is_file():
        raise UserChatError("附件不存在或已过期")
    return path, extension


def _image_data_url(url: str, user_id: int) -> str:
    """将用户上传图片 URL 校验并转为可内联的 data URL（模型 API 无法回取本地地址）。"""
    path, extension = _resolve_upload_path(url, user_id, IMAGE_MIME)
    data = path.read_bytes()
    if not 0 < len(data) <= 8 * 1024 * 1024:
        raise UserChatError("图片附件为空或超过 8MB 限制")
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{IMAGE_MIME[extension]};base64,{encoded}"


def _document_refs(raw) -> list[dict]:
    """解析文档附件，支持 [{\"url\",\"name\"}] 或 [\"url\"]，最多 4 个。"""
    if not isinstance(raw, list):
        return []
    refs: list[dict] = []
    for item in raw:
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
            name = str(item.get("name") or "").strip()
        else:
            url = str(item or "").strip()
            name = ""
        if url:
            refs.append({"url": url, "name": name})
    return refs[:MAX_DOCS]


def _extract_pdf_text(data: bytes) -> str:
    """用 PyPDF2 抽取 PDF 文本，最多前 50 页且受字符预算约束。"""
    try:
        from io import BytesIO

        from PyPDF2 import PdfReader
    except ImportError as exc:
        raise UserChatError("服务器缺少 PDF 解析组件，请联系管理员") from exc
    try:
        reader = PdfReader(BytesIO(data))
        parts: list[str] = []
        total = 0
        for page in reader.pages[:50]:
            text = (page.extract_text() or "").strip()
            if text:
                parts.append(text)
                total += len(text)
            if total > MAX_DOC_CHARS:
                break
        return "\n".join(parts)
    except UserChatError:
        raise
    except Exception as exc:
        raise UserChatError("PDF 解析失败，请确认文件未加密或损坏") from exc


def _document_text(ref: dict, user_id: int) -> dict:
    """校验文档附件并抽取文本（PDF 走 PyPDF2，其余按 UTF-8 解码）。"""
    path, extension = _resolve_upload_path(ref["url"], user_id, DOC_EXT)
    data = path.read_bytes()
    if not 0 < len(data) <= MAX_DOC_BYTES:
        raise UserChatError("文档附件为空或超过 8MB 限制")
    if extension == "pdf":
        text = _extract_pdf_text(data)
    else:
        text = data.decode("utf-8", errors="ignore")
    text = text.strip()
    if not text:
        raise UserChatError("未能从文档中提取到文本内容")
    return {"name": ref.get("name") or path.name, "text": text[:MAX_DOC_CHARS]}


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

        image_urls = _image_urls(payload.get("images"))
        image_data_urls = [_image_data_url(url, user_id) for url in image_urls]
        document_refs = _document_refs(payload.get("documents"))
        documents = [_document_text(ref, user_id) for ref in document_refs]
        documents_text = ""
        if documents:
            blocks: list[str] = []
            budget = MAX_DOC_CHARS
            for doc in documents:
                if budget <= 0:
                    break
                snippet = doc["text"][:budget]
                budget -= len(snippet)
                blocks.append(f"【{doc['name']}】\n{snippet}")
            documents_text = "\n\n".join(blocks)

        model = ModelRepository.get(model_id) if model_id else SystemSettingsService.get_default_model()
        if image_data_urls:
            if employee_id:
                raise UserChatError("图片输入请先取消数字员工调度后再上传")
            if not (model and model.get("enabled") and model.get("vision_enabled")):
                model = ModelRepository.get_for_capability("vision")
            if not model:
                raise UserChatError("当前没有配置支持图片理解的模型，请联系管理员启用视觉能力")
            employee = None
            employee_id = None
        elif documents_text:
            if employee_id:
                raise UserChatError("文档输入请先取消数字员工调度后再上传")
            if not (model and model.get("enabled") and model.get("model_type") in {"text", "multimodal"}):
                model = SystemSettingsService.get_default_model()
            if not (model and model.get("enabled") and model.get("model_type") in {"text", "multimodal"}):
                raise UserChatError("当前没有配置可用于文档理解的文本模型，请联系管理员")
            employee = None
            employee_id = None
        elif model and (not model.get("enabled") or model.get("model_type") not in {"text", "multimodal"}):
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
        user_metadata = {"model_id": selected_model_id, "employee_id": employee_id}
        attachments_meta = [{"url": url, "kind": "image"} for url in image_urls]
        attachments_meta += [
            {"url": ref["url"], "name": doc["name"], "kind": "doc"}
            for ref, doc in zip(document_refs, documents, strict=True)
        ]
        if attachments_meta:
            user_metadata["attachments"] = attachments_meta
        user_message_id = ConversationRepository.add_message(
            conversation_id, "user", prompt, "text", user_metadata
        )
        user_security = OpinionSecurityService.analyze_and_record(
            "chat", user_message_id, prompt, user_id,
            {"conversation_id": conversation_id, "role": "user"},
        )
        ConversationRepository.update_message_security(user_message_id, user_security)

        try:
            result = await UserChatService._answer(
                prompt, conversation_id, user_id, employee, model, on_delta, image_data_urls, documents_text
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
    async def _answer(prompt, conversation_id, user_id, employee, model, on_delta=None, images=None, documents_text="") -> dict:
        QueryIntentService.validate(prompt)
        try:
            validate_untrusted_content(prompt, "用户问题")
            if documents_text:
                validate_untrusted_content(documents_text, "上传文档")
        except PromptInjectionError as exc:
            raise UnsafeQueryError(str(exc)) from exc
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

        if not images and not documents_text:
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
        try:
            if context:
                validate_untrusted_content(context, "会话上下文")
        except PromptInjectionError as exc:
            raise UnsafeQueryError(str(exc)) from exc
        segments = []
        if documents_text:
            segments.append(
                "以下是用户上传的文档内容，请结合它回答：\n"
                + wrap_untrusted_content("uploaded_documents", documents_text)
            )
        if context:
            segments.append(
                "当前会话上下文：\n"
                + wrap_untrusted_content("conversation_history", context)
            )
        tail = "用户最新问题：\n" + wrap_untrusted_content("user_query", prompt)
        head = "\n\n".join(segments)
        budget = PROMPT_LIMIT - len(tail) - 2
        if head and len(head) > budget:
            head = head[:max(budget, 0)]
        full_prompt = f"{head}\n\n{tail}" if head else tail
        safe_model = dict(model)
        safe_model["system_prompt"] = add_untrusted_policy(
            str(safe_model.get("system_prompt") or "")
        )
        result = await (
            LLMService.complete_stream(safe_model, full_prompt, on_delta, images=images)
            if on_delta else LLMService.complete(safe_model, full_prompt, images=images)
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
