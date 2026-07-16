"""用户认证与注册业务规则。"""

from __future__ import annotations

import re

from app.core.exceptions import AuthenticationError, ConflictError, ValidationError
from app.repositories.menu_repository import MenuRepository
from app.repositories.role_repository import RoleRepository
from app.repositories.user_repository import UserRepository

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff]{3,20}$")


class UserService:
    @staticmethod
    def authenticate(username: str, password: str, access_scope: str) -> dict:
        """验证账号并限制其登录端侧。"""
        if not username or not password:
            raise ValidationError("用户名和密码不能为空")
        user = UserRepository.authenticate(username, password)
        if not user or user["role_scope"] != access_scope:
            raise AuthenticationError("用户名或密码错误")
        return user

    @staticmethod
    def register(username: str, password: str, password_confirm: str) -> None:
        """校验并创建普通用户。"""
        if not USERNAME_PATTERN.fullmatch(username):
            raise ValidationError("用户名需为 3—20 位中文、字母、数字或下划线")
        if not 6 <= len(password) <= 64:
            raise ValidationError("密码长度需为 6—64 位")
        if password != password_confirm:
            raise ValidationError("两次输入的密码不一致")
        if not UserRepository.create_user(username, password, role="user"):
            raise ConflictError("该用户名已存在，请更换后重试")

    @staticmethod
    def admin_landing_path(user: dict) -> str | None:
        """返回管理员实际获权的第一个后台页面。"""
        if RoleRepository.has_feature(user["role_id"], "dashboard"):
            return "/admin/"
        menus = MenuRepository.list_for_role(user["role_id"])
        return menus[0]["route"] if menus else None
