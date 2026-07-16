"""Controller 公共基础类：请求跟踪、鉴权、错误和 JSON 契约。"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import uuid

import tornado.web

from app.core.contracts import error_response, success_response
from app.core.permissions import require_admin, require_login, require_permission, require_superadmin
from app.repositories.menu_repository import MenuRepository
from app.repositories.role_repository import RoleRepository
from app.repositories.user_repository import UserRepository

REQUEST_LOGGER = logging.getLogger("request")


class BaseHandler(tornado.web.RequestHandler):
    """统一提供用户 Cookie、request_id、请求日志和 HTML 错误页。"""

    def initialize(self) -> None:
        self.request_id = self.request.headers.get("X-Request-ID", uuid.uuid4().hex)
        self.request_started = time.monotonic()
        self.set_header("X-Request-ID", self.request_id)

    def get_current_user(self):
        raw_user_id = self.get_secure_cookie("user_id", max_age_days=1)
        if not raw_user_id:
            return None
        try:
            return UserRepository.get_user_by_id(int(raw_user_id.decode("utf-8")))
        except (TypeError, ValueError, UnicodeDecodeError):
            self.clear_cookie("user_id")
            return None

    def login_user(self, user: dict) -> None:
        self.set_secure_cookie("user_id", str(user["id"]), expires_days=1, httponly=True, samesite="Lax")

    def logout_user(self) -> None:
        self.clear_cookie("user_id")

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
        user = require_login(self)
        if user["role_scope"] != "user" or not RoleRepository.has_feature(user["role_id"], "user_portal"):
            raise tornado.web.HTTPError(403, reason="当前账号没有用户端访问权限")
