"""Controller 公共基础类：请求跟踪、鉴权、错误和 JSON 契约。"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import uuid

import tornado.web

from app.core.contracts import error_response, success_response
from app.core.permissions import (
    require_admin,
    require_login,
    require_permission,
    require_superadmin,
)
from app.repositories.menu_repository import MenuRepository
from app.repositories.role_repository import RoleRepository
from app.repositories.user_repository import UserRepository
from app.services.system_settings import SystemSettingsService
from config.settings import SETTINGS

REQUEST_LOGGER = logging.getLogger("request")


class BaseHandler(tornado.web.RequestHandler):
    """统一提供用户 Cookie、request_id、请求日志和 HTML 错误页。"""

    def initialize(self) -> None:
        self.request_id = self.request.headers.get("X-Request-ID", uuid.uuid4().hex)
        self.request_started = time.monotonic()
        self.set_header("X-Request-ID", self.request_id)
        self._set_security_headers()

    def prepare(self) -> None:
        if (
            SystemSettingsService.is_maintenance_mode()
            and not self.request.path.startswith("/admin")
            and self.request.path not in {"/", "/login", "/logout"}
        ):
            raise tornado.web.HTTPError(503, reason="系统正在维护，请稍后再试")

    def _set_security_headers(self) -> None:
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("X-Frame-Options", "DENY")
        self.set_header("X-XSS-Protection", "1; mode=block")
        self.set_header("Referrer-Policy", "strict-origin-when-cross-origin")
        if SETTINGS.app_env == "production":
            self.set_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    def get_client_ip(self) -> str:
        for header in ("X-Forwarded-For", "X-Real-IP", "X-Client-IP"):
            value = self.request.headers.get(header)
            if value:
                return value.split(",")[0].strip()
        return self.request.remote_ip

    def get_current_user(self):
        timeout_minutes = SystemSettingsService.get_integer("session_timeout_minutes", 1440)
        max_age_days = timeout_minutes / 1440.0
        raw_user_id = self.get_secure_cookie("user_id", max_age_days=max_age_days)
        if not raw_user_id:
            return None
        # 校验 session_start 是否超时
        raw_session_start = self.get_secure_cookie("session_start", max_age_days=max_age_days)
        if raw_session_start:
            try:
                session_start = int(raw_session_start.decode("utf-8"))
                elapsed = time.time() - session_start
                if elapsed > timeout_minutes * 60:
                    self.clear_cookie("user_id")
                    self.clear_cookie("session_start")
                    return None
            except (TypeError, ValueError, UnicodeDecodeError):
                pass
        try:
            return UserRepository.get_user_by_id(int(raw_user_id.decode("utf-8")))
        except (TypeError, ValueError, UnicodeDecodeError):
            self.clear_cookie("user_id")
            self.clear_cookie("session_start")
            return None

    def login_user(self, user: dict) -> None:
        timeout_minutes = SystemSettingsService.get_integer("session_timeout_minutes", 1440)
        expires_days = timeout_minutes / 1440.0
        self.set_secure_cookie("user_id", str(user["id"]), expires_days=expires_days, httponly=True, samesite="Strict", secure=SETTINGS.app_env == "production")
        self.set_secure_cookie("session_start", str(int(time.time())), expires_days=expires_days, httponly=True, samesite="Strict", secure=SETTINGS.app_env == "production")

    def logout_user(self) -> None:
        self.clear_cookie("user_id")
        self.clear_cookie("session_start")

    def on_finish(self) -> None:
        user = self.current_user
        REQUEST_LOGGER.info(
            "%s %s status=%s duration_ms=%s",
            self.request.method,
            self.request.path,
            self.get_status(),
            round((time.monotonic() - self.request_started) * 1000),
            extra={"request_id": self.request_id, "user_id": user.get("id", "-") if user else "-", "event": "request_finished"},
        )
        if (
            self.request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and user
            and user.get("role_scope") == "admin"
            and (self.request.path.startswith("/admin/") or self.request.path.startswith("/api/admin/"))
            and self.request.path not in {"/admin/login", "/admin/logout"}
        ):
            from app.services.security import AuditLogService

            raw_action = ""
            values = self.request.arguments.get("action") or []
            if values:
                raw_action = values[0].decode("utf-8", errors="ignore").lower()
            if raw_action == "batch":
                batch_values = self.request.arguments.get("batch_action") or []
                if batch_values:
                    raw_action = batch_values[0].decode("utf-8", errors="ignore").lower()
            lowered_path = self.request.path.lower()
            if self.request.method == "DELETE" or "delete" in raw_action or "/delete" in lowered_path:
                action_type = "delete"
            elif any(
                word in f"{raw_action} {lowered_path}"
                for word in ("update", "save", "toggle", "archive", "enable", "disable", "default", "cancel", "retry")
            ):
                action_type = "update"
            else:
                action_type = "create" if self.request.method == "POST" else "update"
            segments = [segment for segment in self.request.path.split("/") if segment]
            admin_index = segments.index("admin") if "admin" in segments else 0
            resource_type = segments[admin_index + 1] if len(segments) > admin_index + 1 else "system"
            resource_id = next(
                (int(segment) for segment in reversed(segments) if re.fullmatch(r"[1-9][0-9]*", segment)),
                None,
            )
            if resource_id is None:
                for key, raw_values in self.request.arguments.items():
                    if key == "id" or key.endswith("_id"):
                        candidate = raw_values[0].decode("utf-8", errors="ignore") if raw_values else ""
                        if candidate.isdecimal() and int(candidate) > 0:
                            resource_id = int(candidate)
                            break
            if resource_id is None and self.request.headers.get("Content-Type", "").startswith("application/json"):
                try:
                    body = json.loads(self.request.body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    body = {}
                if isinstance(body, dict):
                    for key, value in body.items():
                        if (key == "id" or key.endswith("_id")) and str(value).isdecimal() and int(value) > 0:
                            resource_id = int(value)
                            break
            location = self._headers.get("Location", "")
            business_success = self.get_status() < 400 and "level=error" not in location
            try:
                AuditLogService.log_action(
                    action_type=action_type,
                    resource_type=resource_type[:80],
                    resource_id=resource_id,
                    user_id=user["id"],
                    user_name=user.get("username", ""),
                    ip_address=self.get_client_ip(),
                    detail=f"{self.request.method} {self.request.path}; status={self.get_status()}; request_id={self.request_id}",
                    success=business_success,
                    error_message="" if business_success else f"操作失败（HTTP {self.get_status()}）",
                )
            except Exception:
                REQUEST_LOGGER.exception(
                    "audit logging failed without affecting business response",
                    extra={"request_id": self.request_id, "event": "audit_log_failed"},
                )

    def write_error(self, status_code: int, **kwargs) -> None:
        if status_code >= 500:
            REQUEST_LOGGER.error(
                "unhandled page error status=%s path=%s",
                status_code,
                self.request.path,
                exc_info=kwargs.get("exc_info"),
                extra={"request_id": self.request_id, "event": "page_error"},
            )
        messages = {403: ("无权访问", "当前账号没有该功能的访问权限。"), 404: ("页面不存在", "请求的页面可能已移动、被禁用或尚未开放。")}
        title, message = messages.get(status_code, ("系统暂时不可用", "请稍后重试或返回系统首页。"))
        self.set_header("Content-Type", "text/html; charset=UTF-8")
        self.finish(
            "<!doctype html><meta charset='utf-8'><style>body{font-family:system-ui;background:#071426;color:#e6f1ff;display:grid;place-items:center;height:100vh;margin:0}main{padding:40px;border:1px solid #244968;border-radius:10px;background:#102a46}a{color:#7eb0d6}</style>"
            f"<main><h1>{status_code} · {title}</h1><p>{message}</p><p>请求编号：{self.request_id}</p><a href='/'>返回系统首页</a></main>"
        )


class AdminBaseHandler(BaseHandler):
    required_feature: str | None = None

    def get_login_url(self) -> str:
        return "/admin/login"

    def prepare(self) -> None:
        if not self.current_user:
            next_url = urllib.parse.quote(self.request.uri, safe="/")
            self.redirect(f"/admin/login?next={next_url}")
            return
        require_admin(self)
        if self.required_feature:
            require_permission(self, self.required_feature)

    def require_superadmin(self) -> None:
        require_superadmin(self)

    def render_admin(self, template_name: str, *, title: str, active_menu: str, **kwargs) -> None:
        kwargs.setdefault("can_write", bool(self.current_user.get("is_superadmin")))
        self.render(
            template_name,
            title=title,
            page_title=title.split(" · ", 1)[0],
            user=self.current_user,
            active_menu=active_menu,
            admin_menu_groups=MenuRepository.grouped_for_role(self.current_user["role_id"]),
            flash_message=self.get_query_argument("message", ""),
            flash_level=self.get_query_argument("level", "success"),
            xsrf_token=self.xsrf_token,
            **kwargs,
        )

    def redirect_with_message(self, path: str, message: str, level: str = "success") -> None:
        self.redirect(f"{path}?{urllib.parse.urlencode({'message': message, 'level': level})}")


class JsonResponseMixin:
    def json_body(self) -> dict:
        try:
            payload = json.loads(self.request.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise tornado.web.HTTPError(400, reason="请求 JSON 格式不正确") from exc
        if not isinstance(payload, dict):
            raise tornado.web.HTTPError(400, reason="请求体必须是 JSON 对象")
        return payload

    def write_json(self, payload: dict, status: int = 200) -> None:
        self.set_status(status)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        if "success" not in payload:
            envelope = success_response(payload, payload.get("message", "ok"), self.request_id)
            envelope.update(payload)
            payload = envelope
        self.finish(json.dumps(payload, ensure_ascii=False))

    def write_error(self, status_code: int, **kwargs) -> None:
        if status_code >= 500:
            REQUEST_LOGGER.error(
                "unhandled api error status=%s path=%s",
                status_code,
                self.request.path,
                exc_info=kwargs.get("exc_info"),
                extra={"request_id": self.request_id, "event": "api_error"},
            )
        reason = getattr(kwargs.get("exc_info", (None, None, None))[1], "reason", "")
        messages = {400: "请求参数不正确", 401: "请先登录", 403: "当前账号没有该操作权限", 404: "请求的资源不存在"}
        message = reason or messages.get(status_code, "服务暂时不可用")
        code = {400: "VALIDATION_ERROR", 401: "AUTHENTICATION_REQUIRED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND"}.get(status_code, "APP_ERROR")
        payload = error_response(code, message, self.request_id)
        payload.update({"ok": False, "message": message})
        self.set_status(status_code)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.finish(json.dumps(payload, ensure_ascii=False))


class AdminJsonHandler(JsonResponseMixin, AdminBaseHandler):
    def prepare(self) -> None:
        require_admin(self)
        if self.required_feature:
            require_permission(self, self.required_feature)


class UserJsonHandler(JsonResponseMixin, BaseHandler):
    def prepare(self) -> None:
        BaseHandler.prepare(self)
        user = require_login(self)
        if user["role_scope"] != "user" or not RoleRepository.has_feature(user["role_id"], "user_portal"):
            raise tornado.web.HTTPError(403, reason="当前账号没有用户端访问权限")
