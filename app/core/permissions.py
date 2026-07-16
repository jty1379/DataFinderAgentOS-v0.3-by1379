"""页面和接口共用的后端权限校验入口。"""

from __future__ import annotations

import logging
from typing import Any

import tornado.web

from app.repositories.feature_repository import FeatureRepository
from app.repositories.role_repository import RoleRepository

SECURITY_LOGGER = logging.getLogger("security")


def _deny(handler: tornado.web.RequestHandler, status: int, reason: str) -> None:
    user = getattr(handler, "current_user", None)
    SECURITY_LOGGER.warning(
        "permission denied method=%s path=%s reason=%s",
        handler.request.method,
        handler.request.path,
        reason,
        extra={"request_id": getattr(handler, "request_id", "-"), "user_id": user.get("id", "-") if user else "-", "event": "permission_denied"},
    )
    raise tornado.web.HTTPError(status, reason=reason)


def require_login(handler: tornado.web.RequestHandler) -> dict[str, Any]:
    user = handler.current_user
    if not user:
        _deny(handler, 401, "请先登录")
    return user


def require_admin(handler: tornado.web.RequestHandler) -> dict[str, Any]:
    user = require_login(handler)
    if user.get("role_scope") != "admin":
        _deny(handler, 403, "当前账号没有管理端访问权限")
    return user


def require_permission(handler: tornado.web.RequestHandler, permission_code: str) -> dict[str, Any]:
    user = require_admin(handler)
    if not RoleRepository.has_feature(user["role_id"], permission_code):
        _deny(handler, 403, f"缺少功能权限: {permission_code}")
    return user


def require_superadmin(handler: tornado.web.RequestHandler) -> dict[str, Any]:
    user = require_admin(handler)
    if not user.get("is_superadmin"):
        _deny(handler, 403, "仅默认超级管理员可以执行此操作")
    return user


def current_user_permissions(handler: tornado.web.RequestHandler) -> set[str]:
    user = require_login(handler)
    feature_ids = set(RoleRepository.feature_ids(user["role_id"]))
    return {item["code"] for item in FeatureRepository.list_features() if item["id"] in feature_ids}
