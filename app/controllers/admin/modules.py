"""尚未独立实现的后台模块占位与旧路由兼容。"""

import tornado.web

from app.controllers.base import AdminBaseHandler
from app.repositories.role_repository import RoleRepository


class AdminModuleHandler(AdminBaseHandler):
    LEGACY_REDIRECTS = {
        "lookout": "/admin/lookout",
        "data": "/admin/warehouse",
        "collect": "/admin/sources",
        "models": "/admin/models",
    }
    FEATURE_MAP = {
        "lookout": ("lookout_management", "瞭望采集", "该旧地址已迁移到独立采集工作台。"),
        "data": ("data_management", "数据仓库", "该旧地址已迁移到独立数据仓库。"),
        "collect": ("collection_management", "瞭源管理", "该旧地址已迁移到独立瞭源管理。"),
        "agents": ("digital_employees", "数字员工", "当前保留用户侧演示入口。"),
        "models": ("model_engine", "模型引擎", "该旧地址已迁移到独立模型引擎。"),
        "intelligence": ("intelligence_screen", "数智大屏", "大屏模板将在后续版本独立开发。"),
        "opinion": ("opinion_screen", "舆情大屏", "真实舆情采集与分析不在本次范围。"),
    }

    def get(self, module: str) -> None:
        if module in self.LEGACY_REDIRECTS:
            self.redirect(self.LEGACY_REDIRECTS[module], permanent=True)
            return
        item = self.FEATURE_MAP.get(module)
        if not item:
            raise tornado.web.HTTPError(404)
        code, title, note = item
        if not RoleRepository.has_feature(self.current_user["role_id"], code):
            raise tornado.web.HTTPError(403)
        self.render_admin(
            "admin/module.html",
            title=f"{title} · 零界",
            active_menu=code,
            module_title=title,
            module_note=note,
        )
