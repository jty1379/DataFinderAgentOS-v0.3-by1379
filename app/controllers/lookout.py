"""瞭望采集页面与异步采集接口。"""

from __future__ import annotations

import logging

from app.controllers.base import AdminBaseHandler, AdminJsonHandler
from app.models.lookout import CollectionRepository
from app.models.source import RuleRepository
from app.services.collector import CollectorService

LOGGER = logging.getLogger("collection")


def _positive_int(value: str, *, default: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(1, number))


class AdminLookoutHandler(AdminBaseHandler):
    required_feature = "lookout_management"

    def get(self):
        available_rules, _ = RuleRepository.list(
            enabled_only=True, page=1, page_size=200
        )
        recent_runs = CollectionRepository.list_runs(limit=6)
        status_text = {
            "pending": "等待中",
            "running": "采集中",
            "success": "已完成",
            "failed": "失败",
        }
        for run in recent_runs:
            run["status_text"] = status_text.get(run["status"], run["status"])
        self.render_admin(
            "admin/lookout.html",
            title="瞭望采集 · 瞭望与问数系统",
            active_menu="lookout_management",
            available_rules=available_rules,
            recent_runs=recent_runs,
            can_write=True,
        )


class AdminLookoutCollectHandler(AdminJsonHandler):
    required_feature = "lookout_management"

    async def post(self):
        keyword = self.get_body_argument("keyword", "").strip()
        if not 1 <= len(keyword) <= 80:
            return self.write_json(
                {"ok": False, "message": "请输入 1—80 个字符的采集关键词"}, 400
            )
        try:
            rule_id = int(self.get_body_argument("rule_id", "0"))
        except ValueError:
            return self.write_json({"ok": False, "message": "采集规则无效"}, 400)
        page = _positive_int(
            self.get_body_argument("page", "1"), default=1, maximum=100
        )
        page_size = _positive_int(
            self.get_body_argument("page_size", "12"), default=12, maximum=12
        )
        rule = RuleRepository.get(rule_id)
        if not rule or not rule.get("enabled") or not rule.get("source_enabled"):
            return self.write_json(
                {"ok": False, "message": "采集规则或所属瞭源当前不可用"}, 404
            )

        run_id = CollectionRepository.create_run(
            rule_id=rule_id,
            user_id=self.current_user["id"],
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        try:
            items = await CollectorService.collect(
                rule, keyword, page=page, page_size=page_size
            )
            saved_items = CollectionRepository.save_results(run_id, items)
            message = (
                f"采集完成，共获取 {len(saved_items)} 条公开结果"
                if saved_items
                else "请求成功，但页面未解析到结果；站点结构可能已变化"
            )
            return self.write_json(
                {
                    "ok": True,
                    "message": message,
                    "run_id": run_id,
                    "items": saved_items,
                }
            )
        except Exception as exc:  # 外部站点错误需要转换成可恢复反馈
            LOGGER.exception("lookout collection failed", extra={"task_id": run_id, "user_id": self.current_user["id"], "request_id": self.request_id, "event": "lookout_collection_failed"})
            message = str(exc)[:300] or "外部站点暂时不可用"
            CollectionRepository.fail_run(run_id, message)
            return self.write_json(
                {"ok": False, "message": f"采集失败：{message}", "run_id": run_id},
                502,
            )
