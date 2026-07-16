"""管理工作台、数智大屏与舆情大屏控制器。"""

from __future__ import annotations

import tornado.web

from app.controllers.base import AdminBaseHandler, AdminJsonHandler
from app.models.dashboard import DashboardRepository


class AdminDashboardApiHandler(AdminJsonHandler):
    required_feature = "dashboard"

    def get(self) -> None:
        self.write_json({"ok": True, "dashboard": DashboardRepository.overview()})


class IntelligenceScreenHandler(AdminBaseHandler):
    required_feature = "intelligence_screen"

    def get(self) -> None:
        self.render_admin(
            "admin/intelligence_screen.html",
            title="数智大屏 · 瞭望与问数系统",
            active_menu="intelligence_screen",
        )


class IntelligenceScreenApiHandler(AdminJsonHandler):
    required_feature = "intelligence_screen"

    def get(self) -> None:
        self.write_json({"ok": True, "screen": DashboardRepository.intelligence()})


class OpinionScreenHandler(AdminBaseHandler):
    required_feature = "opinion_screen"

    def get(self) -> None:
        self.render_admin(
            "admin/opinion_screen.html",
            title="舆情大屏 · 瞭望与问数系统",
            active_menu="opinion_screen",
        )


class OpinionScreenApiHandler(AdminJsonHandler):
    required_feature = "opinion_screen"

    def get(self) -> None:
        self.write_json({"ok": True, "screen": DashboardRepository.opinion()})


class OpinionAlertActionHandler(AdminJsonHandler):
    required_feature = "opinion_screen"

    def post(self, alert_id: str) -> None:
        payload = self.json_body()
        try:
            changed = DashboardRepository.update_alert(
                int(alert_id),
                str(payload.get("status") or ""),
                str(payload.get("note") or ""),
                self.current_user["id"],
            )
        except ValueError as exc:
            raise tornado.web.HTTPError(400, reason=str(exc)) from exc
        if not changed:
            raise tornado.web.HTTPError(404, reason="预警不存在")
        self.write_json({"ok": True, "message": "预警处理状态已更新"})
