"""用户注册、用户登录和管理端登录。"""

from __future__ import annotations

import re

import tornado.web

from app.controllers.base import BaseHandler
from app.models.rbac import MenuRepository, RoleRepository
from app.models.user import UserRepository


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff]{3,20}$")


def _admin_landing_path(user: dict) -> str | None:
    """Return the first page an administrator role is actually allowed to view.

    A delegated administrator may own only ``user_management`` and therefore
    cannot be sent blindly to the dashboard.  This is the Task 2.1 login fix.
    """
    if RoleRepository.has_feature(user["role_id"], "dashboard"):
        return "/admin/"
    menus = MenuRepository.list_for_role(user["role_id"])
    return menus[0]["route"] if menus else None


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
        user = UserRepository.authenticate(username, password)
        if not user or user["role_scope"] != "user":
            return self.render(
                "login.html",
                title="用户登录 · 瞭望与问数系统",
                error="用户名或密码错误",
                registered=False,
                username=username,
            )
        self.login_user(user)
        self.redirect("/index")


class RegisterHandler(BaseHandler):
    def get(self):
        if self.current_user:
            return self.redirect("/index" if self.current_user["role_scope"] == "user" else "/admin/")
        self.render(
            "register.html",
            title="创建账号 · 瞭望与问数系统",
            error=None,
            username="",
        )

    def post(self):
        if self.current_user:
            return self.redirect("/index" if self.current_user["role_scope"] == "user" else "/admin/")
        username = self.get_body_argument("username", "").strip()
        password = self.get_body_argument("password", "")
        password_confirm = self.get_body_argument("password_confirm", "")

        error = None
        if not USERNAME_PATTERN.fullmatch(username):
            error = "用户名需为 3—20 位中文、字母、数字或下划线"
        elif len(password) < 6 or len(password) > 64:
            error = "密码长度需为 6—64 位"
        elif password != password_confirm:
            error = "两次输入的密码不一致"
        elif not UserRepository.create_user(username, password, role="user"):
            error = "该用户名已存在，请更换后重试"

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
        user = UserRepository.authenticate(username, password)
        if not user or user["role_scope"] != "admin":
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
        self.login_user(user)
        self.redirect(landing)


class UserLogoutHandler(BaseHandler):
    def get(self):
        self.logout_user()
        self.redirect("/")


class AdminLogoutHandler(BaseHandler):
    def get(self):
        self.logout_user()
        self.redirect("/admin/login")
