"""Controller 公共基础类。"""

from __future__ import annotations

import json
import urllib.parse

import tornado.web

from app.models.rbac import MenuRepository, RoleRepository
from app.models.user import UserRepository


class BaseHandler(tornado.web.RequestHandler):
    """统一提供当前用户、登录 Cookie 和错误响应。"""

    def get_current_user(self):
        raw_user_id = self.get_secure_cookie("user_id", max_age_days=1)
        if not raw_user_id:
            return None
        try:
            return UserRepository.get_user_by_id(int(raw_user_id.decode("utf-8")))
        except (TypeError, ValueError, UnicodeDecodeError):
            self.clear_cookie("user_id")
            return None

    def login_user(self, user) -> None:
        self.set_secure_cookie(
            "user_id", str(user["id"]), expires_days=1, httponly=True, samesite="Lax"
        )

    def logout_user(self) -> None:
        self.clear_cookie("user_id")

    def write_error(self, status_code: int, **kwargs) -> None:
        messages = {
            403: ("无权访问", "当前账号没有该功能的访问权限。"),
            404: ("页面不存在", "请求的页面可能已移动、被禁用或尚未开放。"),
        }
        title, message = messages.get(
            status_code, ("系统暂时不可用", "请稍后重试或返回系统首页。")
        )
        self.set_header("Content-Type", "text/html; charset=UTF-8")
        self.finish(
            "<!doctype html><meta charset='utf-8'>"
            "<style>body{font-family:system-ui;background:#071426;color:#e6f1ff;"
            "display:grid;place-items:center;height:100vh;margin:0}"
            "main{padding:40px;border:1px solid #244968;border-radius:10px;"
            "background:#102a46}a{color:#7eb0d6}</style>"
            f"<main><h1>{status_code} · {title}</h1><p>{message}</p>"
            "<a href='/'>返回系统首页</a></main>"
        )


class AdminBaseHandler(BaseHandler):
    """管理端统一执行身份、端侧和功能授权校验。"""

    required_feature: str | None = None

    def get_login_url(self) -> str:
        return "/admin/login"

    def prepare(self) -> None:
        if not self.current_user:
            next_url = urllib.parse.quote(self.request.uri, safe="/")
            self.redirect(f"/admin/login?next={next_url}")
            return
        if self.current_user["role_scope"] != "admin":
            raise tornado.web.HTTPError(403)
        if self.required_feature and not RoleRepository.has_feature(
            self.current_user["role_id"], self.required_feature
        ):
            raise tornado.web.HTTPError(403)

    def require_superadmin(self) -> None:
        """将高风险权限维护操作限制为默认超级管理员。

        页面级功能授权决定“能否查看”，超级管理员标记决定“能否修改”。
        两层校验分离后，审计员等管理角色可以只读查看而不能伪造 POST。
        """
        if not self.current_user or not self.current_user.get("is_superadmin"):
            raise tornado.web.HTTPError(403, reason="仅默认超级管理员可以执行此操作")

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
        query = urllib.parse.urlencode({"message": message, "level": level})
        self.redirect(f"{path}?{query}")


class AdminJsonHandler(AdminBaseHandler):
    """管理端 JSON/SSE 接口基类，避免异步请求收到登录页 HTML。"""

    def prepare(self) -> None:
        if not self.current_user:
            raise tornado.web.HTTPError(401, reason="请先登录管理端")
        if self.current_user["role_scope"] != "admin":
            raise tornado.web.HTTPError(403)
        if self.required_feature and not RoleRepository.has_feature(
            self.current_user["role_id"], self.required_feature
        ):
            raise tornado.web.HTTPError(403)

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
        self.finish(json.dumps(payload, ensure_ascii=False))

    def write_error(self, status_code: int, **kwargs) -> None:
        reason = getattr(kwargs.get("exc_info", (None, None, None))[1], "reason", "")
        messages = {
            400: "请求参数不正确",
            401: "请先登录管理端",
            403: "当前账号没有该操作权限",
            404: "请求的资源不存在",
        }
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.finish(
            json.dumps(
                {"ok": False, "message": reason or messages.get(status_code, "服务暂时不可用")},
                ensure_ascii=False,
            )
        )


class UserJsonHandler(BaseHandler):
    """用户侧 JSON 接口基类，统一执行登录、端侧和 JSON 错误处理。"""

    def prepare(self) -> None:
        if not self.current_user:
            raise tornado.web.HTTPError(401, reason="请先登录用户端")
        if self.current_user["role_scope"] != "user" or not RoleRepository.has_feature(
            self.current_user["role_id"], "user_portal"
        ):
            raise tornado.web.HTTPError(403)

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
        self.finish(json.dumps(payload, ensure_ascii=False))

    def write_error(self, status_code: int, **kwargs) -> None:
        reason = getattr(kwargs.get("exc_info", (None, None, None))[1], "reason", "")
        messages = {
            400: "请求参数不正确",
            401: "请先登录用户端",
            403: "当前账号没有用户端访问权限",
            404: "会话不存在或不属于当前用户",
        }
        self.set_status(status_code)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.finish(json.dumps({
            "ok": False,
            "message": reason or messages.get(status_code, "服务暂时不可用"),
        }, ensure_ascii=False))
