"""技能管理与数字员工绑定接口。"""

from __future__ import annotations

import json

from app.controllers.base import AdminBaseHandler, AdminJsonHandler
from app.models.digital_employee import DigitalEmployeeRepository
from app.models.skill import EmployeeSkillRepository, SkillRepository


def _page(handler: AdminBaseHandler) -> int:
    try:
        return max(1, int(handler.get_query_argument("page", "1")))
    except ValueError:
        return 1


def _integer(handler: AdminBaseHandler, name: str, default: int = 0) -> int:
    try:
        return int(handler.get_body_argument(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc


def _operation_message(result, success: str) -> tuple[str, str]:
    if isinstance(result, tuple):
        ok, message = result
        return str(message), "success" if ok else "error"
    return (success, "success") if result else ("操作失败，请检查配置是否重复", "error")


class AdminSkillsHandler(AdminBaseHandler):
    required_feature = "skill_management"

    def get(self):
        keyword = self.get_query_argument("q", "").strip()
        status = self.get_query_argument("status", "").strip()
        page = _page(self)
        skills, total = SkillRepository.list(
            keyword=keyword,
            status=status,
            page=page,
            page_size=10,
        )
        for skill in skills:
            skill["tools_json"] = json.dumps(
                skill.get("tools", {}), ensure_ascii=False, indent=2
            )
            skill["triggers_json"] = json.dumps(
                skill.get("triggers", {}), ensure_ascii=False, indent=2
            )
        self.render_admin(
            "admin/skills.html",
            title="技能管理 · 瞭望与问数系统",
            active_menu="skill_management",
            skills=skills,
            keyword=keyword,
            selected_status=status,
            page=page,
            pages=max(1, (total + 9) // 10),
            total=total,
            can_write=True,
        )

    def post(self):
        action = self.get_body_argument("action", "")
        try:
            if action in {"create", "update"}:
                skill_id = _integer(self, "skill_id", 0) if action == "update" else None
                code = self.get_body_argument("code", "").strip()
                name = self.get_body_argument("name", "").strip()
                description = self.get_body_argument("description", "").strip()[:500]
                system_prompt = self.get_body_argument("system_prompt", "").strip()[:10000]
                trigger_condition = self.get_body_argument("trigger_condition", "").strip()
                enabled = self.get_body_argument("enabled", "1") == "1"

                if not 2 <= len(name) <= 60:
                    raise ValueError("技能名称需为 2—60 个字符")

                values = dict(
                    code=code,
                    name=name,
                    description=description,
                    system_prompt=system_prompt,
                    trigger_condition=trigger_condition,
                    tools=self.get_body_argument("tools", "{}"),
                    triggers=self.get_body_argument("triggers", "{}"),
                    enabled=enabled,
                )

                if skill_id:
                    result = SkillRepository.update(skill_id=skill_id, **values)
                    message, level = _operation_message(result, "技能配置已更新")
                else:
                    result = SkillRepository.create(
                        created_by=self.current_user["id"], **values
                    )
                    message, level = _operation_message(result, "技能创建成功")
                return self.redirect_with_message("/admin/skills", message, level)

            skill_id = _integer(self, "skill_id", 0)
            if action == "delete":
                result = SkillRepository.delete(skill_id)
                message, level = _operation_message(result, "技能已删除")
            elif action == "toggle":
                result = SkillRepository.toggle(skill_id)
                message, level = _operation_message(result, "技能状态已更新")
            else:
                raise ValueError("未知操作")
            self.redirect_with_message("/admin/skills", message, level)
        except ValueError as exc:
            self.redirect_with_message("/admin/skills", str(exc), "error")


class AdminSkillBindHandler(AdminBaseHandler):
    required_feature = "skill_management"

    def get(self, skill_id: str):
        try:
            skill_id_int = int(skill_id)
        except ValueError:
            return self.redirect_with_message("/admin/skills", "技能编号不正确", "error")

        skill = SkillRepository.get(skill_id_int)
        if not skill:
            return self.redirect_with_message("/admin/skills", "技能不存在", "error")

        bound_employees = EmployeeSkillRepository.list_by_skill(skill_id_int)
        bound_ids = {emp["id"] for emp in bound_employees}

        available_employees, _ = DigitalEmployeeRepository.list(
            status="enabled",
            page=1,
            page_size=100,
        )

        self.render_admin(
            "admin/skill_bind.html",
            title=f"绑定数字员工 · {skill['name']}",
            active_menu="skill_management",
            skill=skill,
            bound_employees=bound_employees,
            available_employees=available_employees,
            bound_ids=bound_ids,
            can_write=True,
        )

    def post(self, skill_id: str):
        try:
            skill_id_int = int(skill_id)
        except ValueError:
            return self.redirect_with_message("/admin/skills", "技能编号不正确", "error")

        skill = SkillRepository.get(skill_id_int)
        if not skill:
            return self.redirect_with_message("/admin/skills", "技能不存在", "error")

        action = self.get_body_argument("action", "")
        employee_id = _integer(self, "employee_id", 0)

        if action == "bind":
            result = EmployeeSkillRepository.bind(employee_id, skill_id_int)
            message = "绑定成功" if result else "已绑定或绑定失败"
            level = "success" if result else "warning"
        elif action == "unbind":
            result = EmployeeSkillRepository.unbind(employee_id, skill_id_int)
            message = "已解绑" if result else "解绑失败"
            level = "success" if result else "error"
        else:
            message = "未知操作"
            level = "error"

        self.redirect_with_message(f"/admin/skills/{skill_id}/bind", message, level)


class AdminSkillSuggestHandler(AdminJsonHandler):
    required_feature = "skill_management"

    def get(self):
        skills = SkillRepository.all_enabled()
        suggestions = []
        for skill in skills:
            item = {
                "id": skill["id"],
                "code": skill["code"],
                "name": skill["name"],
                "description": skill.get("description", ""),
            }
            suggestions.append(item)
        self.write_json({"ok": True, "data": suggestions})