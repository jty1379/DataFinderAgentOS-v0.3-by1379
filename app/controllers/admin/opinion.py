"""后台舆情安全控制器。"""

from app.controllers.admin.common import integer, pager_context, query_page
from app.controllers.base import AdminBaseHandler
from app.services.opinion import OpinionSecurityService


class AdminOpinionAlertsHandler(AdminBaseHandler):
    required_feature = "opinion_management"

    def get(self) -> None:
        status = self.get_query_argument("status", "").strip()
        risk_level = self.get_query_argument("risk_level", "").strip()
        user_id = self.get_query_argument("user_id", "").strip()
        user_id_int = int(user_id) if user_id.isdecimal() else None
        
        alerts, pager = OpinionSecurityService.get_alerts(status, risk_level, user_id_int, query_page(self), 20)
        stats = OpinionSecurityService.get_alert_stats()
        
        self.render_admin(
            "admin/opinion_alerts.html",
            title="舆情预警 · 瞭望与问数系统",
            active_menu="opinion_management",
            alerts=alerts,
            stats=stats,
            pager=pager_context("/admin/opinion/alerts", pager, status=status, risk_level=risk_level, user_id=user_id),
            selected_status=status,
            selected_risk=risk_level,
        )

    def post(self) -> None:
        self.require_superadmin()
        action = self.get_body_argument("action", "")
        try:
            handlers = {
                "handle": self._handle,
                "batch_handle": self._batch_handle,
                "delete": self._delete,
            }
            if action not in handlers:
                raise ValueError("未知操作")
            message, level = handlers[action]()
            self.redirect_with_message("/admin/opinion/alerts", message, level)
        except ValueError as exc:
            self.redirect_with_message("/admin/opinion/alerts", str(exc), "error")

    def _handle(self) -> tuple[str, str]:
        alert_id = integer(self, "alert_id")
        status = self.get_body_argument("status", "")
        handle_note = self.get_body_argument("handle_note", "")
        if status not in ["pending", "processing", "resolved", "false_positive"]:
            raise ValueError("无效状态")
        if not OpinionSecurityService.handle_alert(alert_id, status, self.current_user["id"], handle_note):
            raise ValueError("处理失败")
        return "预警已处理", "success"

    def _batch_handle(self) -> tuple[str, str]:
        alert_ids = self.get_body_arguments("alert_ids")
        status = self.get_body_argument("status", "")
        if not alert_ids:
            raise ValueError("请至少选择一个预警")
        if status not in ["pending", "processing", "resolved", "false_positive"]:
            raise ValueError("无效状态")
        handled = 0
        for aid in alert_ids:
            try:
                if OpinionSecurityService.handle_alert(int(aid), status, self.current_user["id"]):
                    handled += 1
            except ValueError:
                continue
        return f"已处理 {handled} 个预警", "success"

    def _delete(self) -> tuple[str, str]:
        alert_id = integer(self, "alert_id")
        if not OpinionSecurityService._delete_alert(alert_id):
            raise ValueError("删除失败")
        return "预警已删除", "success"


class AdminSensitiveWordsHandler(AdminBaseHandler):
    required_feature = "opinion_management"

    def get(self) -> None:
        keyword = self.get_query_argument("q", "").strip()
        category = self.get_query_argument("category", "").strip()
        
        words, pager = OpinionSecurityService.get_sensitive_words(keyword, category, query_page(self), 20)
        
        self.render_admin(
            "admin/sensitive_words.html",
            title="敏感词管理 · 瞭望与问数系统",
            active_menu="opinion_management",
            words=words,
            pager=pager_context("/admin/opinion/words", pager, q=keyword, category=category),
            keyword=keyword,
            selected_category=category,
        )

    def post(self) -> None:
        self.require_superadmin()
        action = self.get_body_argument("action", "")
        try:
            handlers = {
                "create": self._create,
                "update": self._update,
                "delete": self._delete,
            }
            if action not in handlers:
                raise ValueError("未知操作")
            message, level = handlers[action]()
            self.redirect_with_message("/admin/opinion/words", message, level)
        except ValueError as exc:
            self.redirect_with_message("/admin/opinion/words", str(exc), "error")

    def _create(self) -> tuple[str, str]:
        word = self.get_body_argument("word", "").strip()
        category = self.get_body_argument("category", "default").strip()
        level = int(self.get_body_argument("level", "1"))
        description = self.get_body_argument("description", "").strip()
        if not word:
            raise ValueError("敏感词不能为空")
        if level not in [1, 2, 3, 4]:
            raise ValueError("风险等级无效")
        if not OpinionSecurityService.add_sensitive_word(word, category, level, description, self.current_user["id"]):
            raise ValueError("添加失败，敏感词可能已存在")
        return "敏感词添加成功", "success"

    def _update(self) -> tuple[str, str]:
        word_id = integer(self, "word_id")
        word = self.get_body_argument("word", "").strip()
        category = self.get_body_argument("category", "default").strip()
        level = int(self.get_body_argument("level", "1"))
        description = self.get_body_argument("description", "").strip()
        enabled = self.get_body_argument("enabled", "1") == "1"
        if not word:
            raise ValueError("敏感词不能为空")
        if level not in [1, 2, 3, 4]:
            raise ValueError("风险等级无效")
        if not OpinionSecurityService.update_sensitive_word(word_id, word, category, level, description, enabled):
            raise ValueError("更新失败")
        return "敏感词已更新", "success"

    def _delete(self) -> tuple[str, str]:
        word_id = integer(self, "word_id")
        if not OpinionSecurityService.delete_sensitive_word(word_id):
            raise ValueError("删除失败")
        return "敏感词已删除", "success"