"""管理端控制器按业务领域拆分后的稳定导入入口。"""

from app.controllers.admin.features import AdminFeaturesHandler
from app.controllers.admin.menus import AdminMenusHandler
from app.controllers.admin.modules import AdminModuleHandler
from app.controllers.admin.roles import AdminRolesHandler
from app.controllers.admin.users import AdminUsersHandler

__all__ = [
    "AdminFeaturesHandler",
    "AdminMenusHandler",
    "AdminModuleHandler",
    "AdminRolesHandler",
    "AdminUsersHandler",
]
