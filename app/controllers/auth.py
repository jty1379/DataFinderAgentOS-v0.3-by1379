"""用户注册、用户登录和管理端登录。"""

from __future__ import annotations

import tornado.web

from app.controllers.base import BaseHandler
from app.core.exceptions import AppError
from app.services.security import AuditLogService
from app.services.system_settings import SystemSettingsService
from app.services.user_service import UserService


def _admin_landing_path(user: dict) -> str | None:
    """Return the first page an administrator role is actually allowed to view.

    A delegated administrator may own only ``user_management`` and therefore
    cannot be sent blindly to the dashboard.  This is the Task 2.1 login fix.
    """
    return UserService.admin_landing_path(user)


class UserLoginHandler(BaseHandler):
    def get(self):
        if self.current_user:
            return self.redirect("/index" if self.current_user["role_scope"] == "user" else "/admin/")
        self.render(
            "login.html",
            title="用户登录 · 瞭望与问数系统",
            error=None,
            registered=self.get_query_argument("registered", "") == "1",
            username="",
        )

    def post(self):
        if self.current_user:
            return self.redirect("/index" if self.current_user["role_scope"] == "user" else "/admin/")
        username = self.get_body_argument("username", "").strip()
        password = self.get_body_argument("password", "")
        if not username or not password:
            return self.render(
                "login.html",
                title="用户登录 · 瞭望与问数系统",
                error="用户名和密码不能为空",
                registered=False,
                username=username,
            )
        try:
            user = UserService.authenticate(username, password, "user")
        except AppError:
            AuditLogService.log_login(0, username, self.get_client_ip(), success=False, error_message="用户名或密码错误")
            return self.render(
                "login.html",
                title="用户登录 · 瞭望与问数系统",
                error="用户名或密码错误",
                registered=False,
                username=username,
            )
        AuditLogService.log_login(user["id"], user["username"], self.get_client_ip(), success=True)
        self.login_user(user)
        self.redirect("/index")


class RegisterHandler(BaseHandler):
    def get(self):
        if self.current_user:
            return self.redirect("/index" if self.current_user["role_scope"] == "user" else "/admin/")
        if not SystemSettingsService.allow_register():
            raise tornado.web.HTTPError(403, reason="系统当前已关闭用户注册")
        self.render(
            "register.html",
            title="创建账号 · 瞭望与问数系统",
            error=None,
            username="",
        )

    def post(self):
        if self.current_user:
            return self.redirect("/index" if self.current_user["role_scope"] == "user" else "/admin/")
        if not SystemSettingsService.allow_register():
            raise tornado.web.HTTPError(403, reason="系统当前已关闭用户注册")
        username = self.get_body_argument("username", "").strip()
        password = self.get_body_argument("password", "")
        password_confirm = self.get_body_argument("password_confirm", "")

        error = None
        try:
            UserService.register(username, password, password_confirm)
        except AppError as exc:
            error = exc.public_message

        if error:
            return self.render(
                "register.html",
                title="创建账号 · 瞭望与问数系统",
                error=error,
                username=username,
            )
        self.redirect("/?registered=1")


class AdminLoginHandler(BaseHandler):
    def get(self):
        if self.current_user and self.current_user["role_scope"] == "admin":
            landing = _admin_landing_path(self.current_user)
            if landing:
                return self.redirect(landing)
        self.render(
            "admin/login.html",
            title="管理端登录 · 瞭望与问数系统",
            error=None,
            username="admin",
        )

    def post(self):
        username = self.get_body_argument("username", "").strip()
        password = self.get_body_argument("password", "")
        try:
            user = UserService.authenticate(username, password, "admin")
        except AppError:
            AuditLogService.log_login(0, username, self.get_client_ip(), success=False, error_message="管理员账号或密码错误")
            return self.render(
                "admin/login.html",
                title="管理端登录 · 瞭望与问数系统",
                error="管理员账号或密码错误",
                username=username,
            )
        landing = _admin_landing_path(user)
        if not landing:
            return self.render(
                "admin/login.html",
                title="管理端登录 · 瞭望与问数系统",
                error="该管理员角色尚未分配可访问功能，请联系超级管理员授权",
                username=username,
            )
        AuditLogService.log_login(user["id"], user["username"], self.get_client_ip(), success=True)
        self.login_user(user)
        self.redirect(landing)


class UserLogoutHandler(BaseHandler):
    def get(self):
        user = self.current_user
        if user:
            AuditLogService.log_logout(user["id"], user["username"], self.get_client_ip())
        self.logout_user()
        self.redirect("/")


class AdminLogoutHandler(BaseHandler):
    def get(self):
        user = self.current_user
        if user:
            AuditLogService.log_logout(user["id"], user["username"], self.get_client_ip())
        self.logout_user()
        self.redirect("/admin/login")
