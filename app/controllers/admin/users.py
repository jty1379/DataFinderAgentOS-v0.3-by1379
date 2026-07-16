"""后台用户管理控制器。"""

from app.controllers.admin.common import USERNAME_PATTERN, integer, pager_context, positive_integers, query_page
from app.controllers.base import AdminBaseHandler
from app.repositories.role_repository import RoleRepository
from app.repositories.user_repository import UserRepository


class AdminUsersHandler(AdminBaseHandler):
    required_feature = "user_management"

    def get(self) -> None:
        keyword = self.get_query_argument("q", "").strip()
        status = self.get_query_argument("status", "").strip()
        raw_role_id = self.get_query_argument("role_id", "")
        role_id = int(raw_role_id) if raw_role_id.isdecimal() else None
        users, pager = UserRepository.paginate_users(keyword, role_id, status, query_page(self), 20)
        self.render_admin(
            "admin/users.html",
            title="用户管理 · 瞭望与问数系统",
            active_menu="user_management",
            users=users,
            roles=RoleRepository.list_roles(),
            pager=pager_context("/admin/users", pager, q=keyword, role_id=role_id, status=status),
            keyword=keyword,
            selected_role_id=role_id or 0,
            selected_status=status,
        )

    def post(self) -> None:
        self.require_superadmin()
        action = self.get_body_argument("action", "")
        try:
            handlers = {
                "change_superadmin_password": self._change_password,
                "create": self._create,
                "batch": self._batch,
                "update": self._update,
                "delete": self._delete,
            }
            if action not in handlers:
                raise ValueError("未知操作")
            message, level = handlers[action]()
            self.redirect_with_message("/admin/users", message, level)
        except ValueError as exc:
            self.redirect_with_message("/admin/users", str(exc), "error")

    def _change_password(self) -> tuple[str, str]:
        current_password = self.get_body_argument("current_password", "")
        new_password = self.get_body_argument("new_password", "")
        confirm_password = self.get_body_argument("confirm_password", "")
        if new_password != confirm_password:
            raise ValueError("两次输入的新密码不一致")
        if current_password == new_password:
            raise ValueError("新密码不能与当前密码相同")
        if not UserRepository.change_superadmin_password(self.current_user["id"], current_password, new_password):
            raise ValueError("当前密码错误，或新密码不符合 6—64 位要求")
        return "超级管理员密码已更新", "success"

    def _create(self) -> tuple[str, str]:
        username = self.get_body_argument("username", "").strip()
        password = self.get_body_argument("password", "")
        role_id = integer(self, "role_id")
        if not USERNAME_PATTERN.fullmatch(username):
            raise ValueError("用户名需为 3—20 位中文、字母、数字或下划线")
        if not 6 <= len(password) <= 64:
            raise ValueError("密码长度需为 6—64 位")
        if not UserRepository.create_user(username, password, role_id=role_id):
            raise ValueError("用户名已存在或所选角色不可用")
        return "用户创建成功", "success"

    def _batch(self) -> tuple[str, str]:
        batch_action = self.get_body_argument("batch_action", "")
        if batch_action not in {"enable", "disable", "delete"}:
            raise ValueError("请选择有效的批量操作")
        user_ids = positive_integers(self.get_body_arguments("user_ids"))
        if not user_ids:
            raise ValueError("请至少选择一个用户")
        changed, message = UserRepository.batch_action(user_ids, batch_action, self.current_user["id"])
        return message, "success" if changed else "error"

    def _target(self) -> tuple[int, dict]:
        user_id = integer(self, "user_id")
        target = next((item for item in UserRepository.list_users() if item["id"] == user_id), None)
        if not target:
            raise ValueError("用户不存在")
        return user_id, target

    def _update(self) -> tuple[str, str]:
        user_id, target = self._target()
        username = self.get_body_argument("username", "").strip()
        password = self.get_body_argument("password", "")
        role_id = integer(self, "role_id")
        status = self.get_body_argument("status", "enabled")
        role = RoleRepository.get(role_id)
        if not USERNAME_PATTERN.fullmatch(username):
            raise ValueError("用户名格式不正确")
        if password and not 6 <= len(password) <= 64:
            raise ValueError("新密码长度需为 6—64 位")
        if status not in {"enabled", "disabled"} or not role:
            raise ValueError("状态或角色无效")
        if target.get("is_superadmin"):
            raise ValueError("默认超级管理员受系统保护，不能在用户列表中修改")
        removes_admin = status != "enabled" or role["access_scope"] != "admin"
        if UserRepository.is_enabled_admin(user_id) and removes_admin and UserRepository.count_enabled_admins() <= 1:
            raise ValueError("必须至少保留一个可用管理员")
        if user_id == self.current_user["id"] and removes_admin:
            raise ValueError("不能停用或降级当前登录账号")
        if not UserRepository.update_user(user_id, username, role_id, status, password):
            raise ValueError("保存失败，用户名可能重复")
        return "用户信息已更新", "success"

    def _delete(self) -> tuple[str, str]:
        user_id, target = self._target()
        if target.get("is_superadmin"):
            raise ValueError("默认超级管理员受系统保护，不能删除")
        if user_id == self.current_user["id"]:
            raise ValueError("不能删除当前登录账号")
        if UserRepository.is_enabled_admin(user_id) and UserRepository.count_enabled_admins() <= 1:
            raise ValueError("必须至少保留一个可用管理员")
        UserRepository.delete_user(user_id)
        return "用户已删除", "success"
