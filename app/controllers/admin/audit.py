"""后台审计日志控制器。"""

import json

from app.controllers.admin.common import pager_context, query_page
from app.controllers.base import AdminBaseHandler
from app.services.security import AuditLogService


class AdminAuditLogsHandler(AdminBaseHandler):
    required_feature = "audit_logs"

    def get(self) -> None:
        action_type = self.get_query_argument("action_type", "").strip()
        user_id = self.get_query_argument("user_id", "").strip()
        user_id_int = int(user_id) if user_id.isdecimal() else None
        
        logs, pager = AuditLogService.get_logs(action_type, user_id_int, query_page(self), 20)
        
        for log in logs:
            try:
                log["action_before"] = json.loads(log.get("action_before") or "{}")
            except json.JSONDecodeError:
                log["action_before"] = {}
            try:
                log["action_after"] = json.loads(log.get("action_after") or "{}")
            except json.JSONDecodeError:
                log["action_after"] = {}
        
        action_types = ["login", "logout", "create", "update", "delete", "query", "export"]
        
        self.render_admin(
            "admin/audit_logs.html",
            title="审计日志 · 瞭望与问数系统",
            active_menu="audit_logs",
            logs=logs,
            action_types=action_types,
            pager=pager_context("/admin/audit/logs", pager, action_type=action_type, user_id=user_id),
            selected_action=action_type,
        )