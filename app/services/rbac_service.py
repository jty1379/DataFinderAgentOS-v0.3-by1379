"""角色授权业务边界。"""

from app.core.exceptions import PermissionDeniedError
from app.repositories.feature_repository import FeatureRepository
from app.repositories.role_repository import RoleRepository


class RbacService:
    @staticmethod
    def permissions_for_role(role_id: int) -> set[str]:
        """返回角色当前有效的权限编码集合。"""
        ids = set(RoleRepository.feature_ids(role_id))
        return {item["code"] for item in FeatureRepository.list_features() if item["id"] in ids and item["enabled"]}

    @staticmethod
    def assert_permission(role_id: int, permission_code: str) -> None:
        """无权限时抛出统一业务异常。"""
        if permission_code not in RbacService.permissions_for_role(role_id):
            raise PermissionDeniedError(f"缺少功能权限: {permission_code}")
