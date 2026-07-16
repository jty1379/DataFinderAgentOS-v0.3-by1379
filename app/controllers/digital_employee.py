"""数字员工管理与后台预览接口。"""

from __future__ import annotations

import json

from app.controllers.base import AdminBaseHandler, AdminJsonHandler
from app.models.digital_employee import DigitalEmployeeRepository
from app.models.interface import InterfaceRepository
from app.models.model_engine import ModelRepository
from app.services.digital_employee import DigitalEmployeeService
from app.services.employee_knowledge import (
    EmployeeKnowledgeError,
    list_files,
    remove_employee_directory,
    save_uploads,
)


def _page(handler: AdminBaseHandler) -> int:
    try:
        return max(1, int(handler.get_query_argument("page", "1")))
    except ValueError:
        return 1


class AdminDigitalEmployeesHandler(AdminBaseHandler):
    required_feature = "digital_employees"

    def get(self):
        keyword = self.get_query_argument("q", "").strip()
        employee_type = self.get_query_argument("type", "").strip()
        status = self.get_query_argument("status", "").strip()
        if employee_type not in {"", "llm", "api"}:
            employee_type = ""
        if status not in {"", "enabled", "disabled"}:
            status = ""
        page = _page(self)
        employees, total = DigitalEmployeeRepository.list(
            keyword=keyword, employee_type=employee_type, status=status,
            page=page, page_size=8,
        )
        for employee in employees:
            employee["prompt_files"] = list_files(employee["id"])
        models, _ = ModelRepository.list(status="enabled", page=1, page_size=100)
        interfaces, _ = InterfaceRepository.list(status="enabled", page=1, page_size=100)
        self.render_admin(
            "admin/digital_employees.html",
            title="数字员工 · 瞭望与问数系统",
            active_menu="digital_employees",
            employees=employees, models=models, interfaces=interfaces, keyword=keyword,
            selected_type=employee_type, selected_status=status,
            page=page, pages=max(1, (total + 7) // 8), total=total,
        )

    def post(self):
        self.require_superadmin()
        action = self.get_body_argument("action", "")
        created_employee_id = None
        try:
            employee_id = int(self.get_body_argument("employee_id", "0") or 0)
            if action in {"create", "update"}:
                values = {
                    "code": self.get_body_argument("code", ""),
                    "name": self.get_body_argument("name", ""),
                    "mention": self.get_body_argument("mention", ""),
                    "employee_type": self.get_body_argument("employee_type", "llm"),
                    "description": self.get_body_argument("description", ""),
                    "model_id": self.get_body_argument("model_id", ""),
                    "interface_id": self.get_body_argument("interface_id", ""),
                    "use_default_model": self.get_body_argument("use_default_model", "0"),
                    "system_prompt": self.get_body_argument("system_prompt", ""),
                    "prompt_template": self.get_body_argument("prompt_template", "{{input}}"),
                    "skills": self.get_body_argument("skills", ""),
                    "crawl4ai_enabled": self.get_body_argument("crawl4ai_enabled", "0"),
                    "crawl4ai_config": self.get_body_argument("crawl4ai_config", "{}"),
                    "api_method": self.get_body_argument("api_method", "GET"),
                    "api_url": self.get_body_argument("api_url", ""),
                    "request_headers": self.get_body_argument("request_headers", "{}"),
                    "request_params": self.get_body_argument("request_params", "{}"),
                    "response_mode": self.get_body_argument("response_mode", "json"),
                    "timeout_seconds": self.get_body_argument("timeout_seconds", "20"),
                    "enabled": self.get_body_argument("enabled", "1"),
                }
                if action == "create":
                    result = DigitalEmployeeRepository.create(
                        created_by=self.current_user["id"], **values
                    )
                    created_employee_id = result or None
                    message = "数字员工创建成功" if result else "编码、名称或 @调度名已存在"
                    level = "success" if result else "error"
                    if result:
                        save_uploads(
                            result,
                            self.request.files.get("prompt_files", []),
                            clear=self.get_body_argument("clear_prompt_files", "0") == "1",
                        )
                else:
                    result = DigitalEmployeeRepository.update(employee_id, **values)
                    message = "数字员工配置已更新" if result else "更新失败，请检查唯一字段"
                    level = "success" if result else "error"
                    if result:
                        save_uploads(
                            employee_id,
                            self.request.files.get("prompt_files", []),
                            clear=self.get_body_argument("clear_prompt_files", "0") == "1",
                        )
            elif action == "delete":
                ok, message = DigitalEmployeeRepository.delete(employee_id)
                level = "success" if ok else "error"
                if ok:
                    remove_employee_directory(employee_id)
            elif action == "toggle":
                ok, message = DigitalEmployeeRepository.toggle(employee_id)
                level = "success" if ok else "error"
            else:
                raise ValueError("未知操作")
        except (TypeError, ValueError, json.JSONDecodeError, EmployeeKnowledgeError) as exc:
            if created_employee_id:
                remove_employee_directory(created_employee_id)
                DigitalEmployeeRepository.delete(created_employee_id)
            message, level = str(exc), "error"
        self.redirect_with_message("/admin/agents", message, level)


class AdminDigitalEmployeePreviewHandler(AdminJsonHandler):
    required_feature = "digital_employees"

    async def post(self):
        payload = self.json_body()
        try:
            employee_id = int(payload.get("employee_id") or 0)
            result = await DigitalEmployeeService.preview(
                employee_id, str(payload.get("input") or ""), self.current_user["id"]
            )
        except (TypeError, ValueError) as exc:
            return self.write_json({"ok": False, "message": str(exc)}, 400)
        return self.write_json({"ok": True, "result": result})


class AdminDigitalEmployeeHealthHandler(AdminJsonHandler):
    required_feature = "digital_employees"

    async def get(self):
        try:
            employee_id = int(self.get_query_argument("id", "0") or 0)
            if not employee_id:
                return self.write_json({"ok": False, "message": "缺少员工ID"}, 400)
            health = await DigitalEmployeeService.health_check(employee_id)
            return self.write_json({"ok": True, "health": health})
        except Exception as exc:
            return self.write_json({"ok": False, "message": str(exc)}, 400)


class AdminDigitalEmployeeLogsHandler(AdminJsonHandler):
    required_feature = "digital_employees"

    async def get(self):
        try:
            employee_id = int(self.get_query_argument("id", "0") or 0)
            limit = min(50, int(self.get_query_argument("limit", "20") or 20))
            if not employee_id:
                return self.write_json({"ok": False, "message": "缺少员工ID"}, 400)
            logs = DigitalEmployeeRepository.list_call_logs(employee_id, limit=limit)
            return self.write_json({"ok": True, "logs": logs})
        except Exception as exc:
            return self.write_json({"ok": False, "message": str(exc)}, 400)
