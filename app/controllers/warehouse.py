"""数据仓库列表与采集结果批量入库。"""

from __future__ import annotations

import tornado.ioloop

from app.controllers.base import AdminBaseHandler, AdminJsonHandler
from app.models.deep_collection import DeepCollectionRepository
from app.models.warehouse import WarehouseRepository
from app.services.deep_collection import DeepCollectionService


def _page(handler: AdminBaseHandler) -> int:
    try:
        return max(1, int(handler.get_query_argument("page", "1")))
    except ValueError:
        return 1


class AdminWarehouseHandler(AdminBaseHandler):
    required_feature = "data_management"

    def get(self):
        keyword = self.get_query_argument("q", "").strip()
        deep_status = self.get_query_argument("deep_status", "").strip()
        if deep_status not in {"", "0", "1", "yes", "no"}:
            deep_status = ""
        page = _page(self)
        items, total = WarehouseRepository.list(
            keyword=keyword,
            deep_status=deep_status,
            page=page,
            page_size=10,
        )
        self.render_admin(
            "admin/warehouse.html",
            title="数据仓库 · 瞭望与问数系统",
            active_menu="data_management",
            items=items,
            keyword=keyword,
            deep_status=deep_status,
            page=page,
            pages=max(1, (total + 9) // 10),
            total=total,
            can_write=True,
        )

    def post(self):
        action = self.get_body_argument("action", "")
        try:
            item_id = int(self.get_body_argument("item_id", "0"))
        except ValueError:
            return self.redirect_with_message("/admin/warehouse", "数据编号不正确", "error")
        if action == "delete":
            result = WarehouseRepository.delete(item_id)
            if isinstance(result, tuple):
                ok, message = result
            else:
                ok, message = bool(result), "仓库数据已删除" if result else "数据不存在"
            return self.redirect_with_message(
                "/admin/warehouse", message, "success" if ok else "error"
            )
        self.redirect_with_message("/admin/warehouse", "未知操作", "error")


class AdminWarehouseImportHandler(AdminJsonHandler):
    required_feature = "data_management"

    def post(self):
        payload = self.json_body()
        raw_ids = payload.get("result_ids", [])
        if not isinstance(raw_ids, list):
            return self.write_json({"ok": False, "message": "请选择要入仓的采集结果"}, 400)
        result_ids: list[int] = []
        for value in raw_ids[:50]:
            try:
                result_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        result_ids = sorted({item for item in result_ids if item > 0})
        if not result_ids:
            return self.write_json({"ok": False, "message": "请至少选择一条采集结果"}, 400)
        inserted, skipped = WarehouseRepository.import_results(
            result_ids=result_ids, user_id=self.current_user["id"]
        )
        return self.write_json(
            {
                "ok": True,
                "message": f"已入仓 {inserted} 条，跳过重复或无效数据 {skipped} 条",
                "inserted": inserted,
                "skipped": skipped,
            }
        )


class AdminWarehouseDeepCollectHandler(AdminJsonHandler):
    required_feature = "data_management"

    def post(self):
        payload = self.json_body()
        raw_ids = payload.get("item_ids", [])
        if not isinstance(raw_ids, list):
            return self.write_json({"ok": False, "message": "请选择要深度采集的数据"}, 400)
        try:
            employee = DeepCollectionService.collector_employee()
            update = bool(payload.get("update", False))
            task_ids, skipped = DeepCollectionRepository.create_tasks(
                raw_ids, employee["id"], self.current_user["id"], update=update
            )
        except ValueError as exc:
            return self.write_json({"ok": False, "message": str(exc)}, 400)
        for task_id in task_ids:
            tornado.ioloop.IOLoop.current().spawn_callback(DeepCollectionService.run, task_id)
        if not task_ids:
            return self.write_json({
                "ok": False,
                "message": "未创建任务：数据可能已完成深采、正在执行或不存在；更新采集请勾选更新模式",
                "skipped": skipped,
            }, 409)
        return self.write_json({
            "ok": True, "task_ids": task_ids, "skipped": skipped,
            "message": f"已创建 {len(task_ids)} 个深度采集任务，跳过 {len(skipped)} 条",
        })


class AdminWarehouseDeepTaskHandler(AdminJsonHandler):
    required_feature = "data_management"

    def get(self, task_id: str):
        try:
            task = DeepCollectionRepository.detail(int(task_id))
        except ValueError:
            task = None
        if not task:
            return self.write_json({"ok": False, "message": "深采任务不存在"}, 404)
        return self.write_json({"ok": True, "task": task})


class AdminWarehouseDeepResultHandler(AdminJsonHandler):
    required_feature = "data_management"

    def get(self, item_id: str):
        try:
            result = DeepCollectionRepository.latest_result(int(item_id))
        except ValueError:
            result = None
        if not result:
            return self.write_json({"ok": False, "message": "该数据尚无深度采集结果"}, 404)
        return self.write_json({"ok": True, "result": result})


class WarehouseStatsHandler(AdminJsonHandler):
    """数据仓库统计接口，供数据分析师数字员工调用。"""

    def get(self):
        period = self.get_query_argument("period", "week").strip().lower()
        if period not in {"today", "week", "month", "all"}:
            period = "week"
        from app.models.db import connection_scope
        with connection_scope() as conn:
            period_clause = ""
            if period == "today":
                period_clause = "AND w.created_at >= date('now', 'start of day')"
            elif period == "week":
                period_clause = "AND w.created_at >= date('now', '-7 days')"
            elif period == "month":
                period_clause = "AND w.created_at >= date('now', '-30 days')"

            total = int(conn.execute(
                "SELECT COUNT(*) AS c FROM warehouse_items w WHERE 1=1 " + period_clause
            ).fetchone()["c"])
            deep_count = int(conn.execute(
                "SELECT COUNT(*) AS c FROM warehouse_items w WHERE w.deep_collected = 1 " + period_clause
            ).fetchone()["c"])
            sources = conn.execute(
                "SELECT w.source_name, COUNT(*) AS cnt FROM warehouse_items w WHERE 1=1 "
                + period_clause + " GROUP BY w.source_name ORDER BY cnt DESC LIMIT 10"
            ).fetchall()
            recent = conn.execute(
                "SELECT w.title, w.source_name, w.created_at FROM warehouse_items w WHERE 1=1 "
                + period_clause + " ORDER BY w.id DESC LIMIT 5"
            ).fetchall()

        return self.write_json({
            "ok": True,
            "period": period,
            "total_items": total,
            "deep_collected": deep_count,
            "deep_rate": round(deep_count / total * 100, 1) if total else 0,
            "sources": [{"name": r["source_name"] or "未知来源", "count": r["cnt"]} for r in sources],
            "recent": [dict(r) for r in recent],
        })
