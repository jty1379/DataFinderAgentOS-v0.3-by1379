"""安全审计服务。"""

from __future__ import annotations

import logging

from app.models.opinion import AuditLogRepository

LOGGER = logging.getLogger("app")


class AuditLogService:
    @staticmethod
    def log_action(
        action_type: str,
        resource_type: str,
        resource_id: int = None,
        user_id: int = None,
        user_name: str = "",
        ip_address: str = "",
        action_before: dict = None,
        action_after: dict = None,
        detail: str = "",
        success: bool = True,
        error_message: str = "",
    ):
        result = AuditLogRepository.create(
            action_type=action_type,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            user_name=user_name,
            ip_address=ip_address,
            action_before=action_before,
            action_after=action_after,
            detail=detail,
            success=success,
            error_message=error_message,
        )
        if result:
            LOGGER.info("审计日志: %s %s %s", action_type, resource_type, resource_id,
                        extra={"event": "audit_log", "action_type": action_type, "resource_type": resource_type})
        return result

    @staticmethod
    def get_logs(action_type: str = "", user_id: int = None, page: int = 1, page_size: int = 20):
        return AuditLogRepository.list_logs(action_type, user_id, page, page_size)

    @staticmethod
    def log_login(user_id: int, user_name: str, ip_address: str, success: bool = True, error_message: str = ""):
        return AuditLogService.log_action(
            action_type="login",
            resource_type="user",
            resource_id=user_id,
            user_id=user_id,
            user_name=user_name,
            ip_address=ip_address,
            success=success,
            error_message=error_message,
        )

    @staticmethod
    def log_logout(user_id: int, user_name: str, ip_address: str):
        return AuditLogService.log_action(
            action_type="logout",
            resource_type="user",
            resource_id=user_id,
            user_id=user_id,
            user_name=user_name,
            ip_address=ip_address,
        )

    @staticmethod
    def log_create(resource_type: str, resource_id: int, user_id: int, user_name: str, data: dict = None):
        return AuditLogService.log_action(
            action_type="create",
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            user_name=user_name,
            action_after=data,
        )

    @staticmethod
    def log_update(resource_type: str, resource_id: int, user_id: int, user_name: str, before: dict = None, after: dict = None):
        return AuditLogService.log_action(
            action_type="update",
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            user_name=user_name,
            action_before=before,
            action_after=after,
        )

    @staticmethod
    def log_delete(resource_type: str, resource_id: int, user_id: int, user_name: str, data: dict = None):
        return AuditLogService.log_action(
            action_type="delete",
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            user_name=user_name,
            action_before=data,
        )