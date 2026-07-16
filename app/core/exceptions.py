"""可安全展示的业务异常层级。"""

from __future__ import annotations


class AppError(Exception):
    code = "APP_ERROR"
    status_code = 500
    default_message = "服务暂时不可用"

    def __init__(self, message: str = "", *, details: dict | None = None) -> None:
        super().__init__(message or self.default_message)
        self.public_message = message or self.default_message
        self.details = details or {}


class ValidationError(AppError):
    code, status_code, default_message = "VALIDATION_ERROR", 400, "请求参数不正确"


class AuthenticationError(AppError):
    code, status_code, default_message = "AUTHENTICATION_REQUIRED", 401, "请先登录"


class PermissionDeniedError(AppError):
    code, status_code, default_message = "PERMISSION_DENIED", 403, "无权执行该操作"


class NotFoundError(AppError):
    code, status_code, default_message = "NOT_FOUND", 404, "请求的资源不存在"


class ConflictError(AppError):
    code, status_code, default_message = "CONFLICT", 409, "资源状态冲突"


class ExternalAPIError(AppError):
    code, status_code, default_message = "EXTERNAL_API_ERROR", 502, "外部服务暂时不可用"


class CollectionError(AppError):
    code, status_code, default_message = "COLLECTION_ERROR", 502, "数据采集失败"


class ModelCallError(AppError):
    code, status_code, default_message = "MODEL_CALL_ERROR", 502, "模型调用失败"


class DatabaseError(AppError):
    code, status_code, default_message = "DATABASE_ERROR", 500, "数据库操作失败"
