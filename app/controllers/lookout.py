"""瞭望采集页面与异步采集接口。"""

from __future__ import annotations

import logging

from app.controllers.base import AdminBaseHandler, AdminJsonHandler
from app.models.source import RuleRepository
from app.services.collection_task import CollectionTaskService

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
        keyword = self.get_query_argument("q", "").strip()
        selected_status = self.get_query_argument("status", "").strip()
        selected_type = self.get_query_argument("task_type", "").strip()
        try:
            selected_rule_id = max(
                0, int(self.get_query_argument("rule_id", "0"))
            )
        except ValueError:
            selected_rule_id = 0
        page = _positive_int(
            self.get_query_argument("task_page", "1"), default=1, maximum=100000
        )
        recent_runs, task_total = CollectionTaskService.list_tasks(
            keyword=keyword,
            status=selected_status,
            task_type=selected_type,
            page=page,
            page_size=12,
        )
        status_text = {
            "pending": "等待中",
            "running": "采集中",
            "success": "已完成",
            "partial": "部分成功",
            "failed": "失败",
            "cancelled": "已取消",
        }
        for run in recent_runs:
            run["status_text"] = status_text.get(run["status"], run["status"])
        self.render_admin(
            "admin/lookout.html",
            title="瞭望采集 · 瞭望与问数系统",
            active_menu="lookout_management",
            available_rules=available_rules,
            recent_runs=recent_runs,
            task_total=task_total,
            task_page=page,
            task_pages=max(1, (task_total + 11) // 12),
            keyword=keyword,
            selected_status=selected_status,
            selected_type=selected_type,
            selected_rule_id=selected_rule_id,
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
        start_page = _positive_int(
            self.get_body_argument("page", "1"), default=1, maximum=100
        )
        pages = _positive_int(
            self.get_body_argument("pages", "1"), default=1, maximum=20
        )
        page_size = _positive_int(
            self.get_body_argument("page_size", "12"), default=12, maximum=12
        )
        task_type = self.get_body_argument("task_type", "single").strip()
        if task_type not in {"single", "batch"}:
            return self.write_json({"ok": False, "message": "采集任务类型无效"}, 400)
        if task_type == "single":
            pages = 1
        rule = RuleRepository.get(rule_id)
        if not rule or not rule.get("enabled") or not rule.get("source_enabled"):
            return self.write_json(
                {"ok": False, "message": "采集规则或所属瞭源当前不可用"}, 404
            )

        try:
            run_id = CollectionTaskService.create_batch_task(
                rule_id,
                keyword,
                pages=pages,
                user_id=self.current_user["id"],
                start_page=start_page,
                page_size=page_size,
            )
            if not run_id:
                return self.write_json(
                    {"ok": False, "message": "采集规则或所属瞭源当前不可用"}, 404
                )
            CollectionTaskService.schedule(run_id)
            return self.write_json(
                {
                    "ok": True,
                    "message": f"采集任务 #{run_id} 已创建，正在后台执行",
                    "run_id": run_id,
                    "task": CollectionTaskService.get_task_progress(run_id),
                },
                202,
            )
        except ValueError as exc:
            return self.write_json({"ok": False, "message": str(exc)}, 400)
        except Exception:
            LOGGER.exception(
                "lookout task create failed",
                extra={
                    "user_id": self.current_user["id"],
                    "request_id": self.request_id,
                    "event": "lookout_task_create_failed",
                },
            )
            return self.write_json(
                {"ok": False, "message": "采集任务创建失败，请检查规则后重试"}, 500
            )


class AdminLookoutTaskHandler(AdminJsonHandler):
    required_feature = "lookout_management"

    def get(self, task_id: str):
        try:
            task = CollectionTaskService.get_task_progress(int(task_id))
        except ValueError:
            task = None
        if not task:
            return self.write_json({"ok": False, "message": "采集任务不存在"}, 404)
        return self.write_json({"ok": True, "task": task})


class AdminLookoutTaskActionHandler(AdminJsonHandler):
    required_feature = "lookout_management"

    def post(self, task_id: str, action: str):
        try:
            task_id_int = int(task_id)
        except ValueError:
            return self.write_json({"ok": False, "message": "采集任务编号无效"}, 400)
        if action == "cancel":
            if not CollectionTaskService.cancel_task(task_id_int):
                return self.write_json(
                    {"ok": False, "message": "只有等待中或运行中的任务可以取消"}, 409
                )
            return self.write_json({"ok": True, "message": "采集任务已取消"})
        if action == "retry":
            if not CollectionTaskService.retry_failed_task(task_id_int):
                return self.write_json(
                    {"ok": False, "message": "只有失败、部分成功或已取消任务可以重试"},
                    409,
                )
            CollectionTaskService.schedule(task_id_int)
            return self.write_json({"ok": True, "message": "采集任务已重新开始"})
        return self.write_json({"ok": False, "message": "不支持的任务操作"}, 400)
