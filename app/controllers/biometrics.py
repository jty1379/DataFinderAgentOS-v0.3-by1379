"""用户人脸档案、人脸登录和多帧手势 API。"""

from __future__ import annotations

import json

import tornado.web

from app.controllers.base import AdminJsonHandler, BaseHandler, UserJsonHandler
from app.models.biometrics import BiometricRepository
from app.models.digital_employee import DigitalEmployeeRepository
from app.models.user import UserRepository
from app.services.biometrics import (
    BiometricError,
    FaceVerifier,
    GestureRecognizer,
    decode_frames,
    dumps_embedding,
    loads_embedding,
)


def _json_payload(handler: BaseHandler) -> dict:
    try:
        value = json.loads(handler.request.body or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise tornado.web.HTTPError(400, reason="请求 JSON 格式不正确") from exc
    if not isinstance(value, dict):
        raise tornado.web.HTTPError(400, reason="请求内容必须是对象")
    return value


def _write(handler: BaseHandler, payload: dict, status: int = 200) -> None:
    handler.set_status(status)
    handler.set_header("Content-Type", "application/json; charset=UTF-8")
    handler.finish(json.dumps(payload, ensure_ascii=False))


class FaceLoginHandler(BaseHandler):
    async def post(self) -> None:
        if not BiometricRepository.face_login_enabled():
            return _write(self, {"ok": False, "message": "系统已停用人脸登录"}, 403)
        payload = _json_payload(self)
        username = str(payload.get("username") or "").strip()
        user = UserRepository.get_active_user_by_username(username)
        if not user or user["role_scope"] != "user":
            return _write(self, {"ok": False, "message": "未找到可用的用户账号"}, 401)
        profile = BiometricRepository.face_profile(user["id"])
        if not profile or not profile["enabled"]:
            return _write(self, {"ok": False, "message": "该账号尚未录入或已停用人脸登录"}, 403)
        try:
            frames = decode_frames(payload.get("frames"), minimum=4, maximum=7)
            candidate, evidence = FaceVerifier.extract_profile(frames)
            similarity = FaceVerifier.compare(loads_embedding(profile["embedding"]), candidate)
        except BiometricError as exc:
            return _write(self, {"ok": False, "message": str(exc)}, 422)
        if similarity < 0.82:
            return _write(self, {"ok": False, "message": "人脸与该账号不匹配"}, 401)
        self.login_user(user)
        _write(
            self,
            {
                "ok": True,
                "redirect": "/index",
                "message": "人脸验证通过",
                "evidence": {**evidence, "similarity": round(similarity, 4)},
            },
        )


class FaceProfileHandler(UserJsonHandler):
    def get(self) -> None:
        profile = BiometricRepository.face_profile(self.current_user["id"])
        self.write_json(
            {
                "ok": True,
                "global_enabled": BiometricRepository.face_login_enabled(),
                "profile": {
                    "enrolled": bool(profile),
                    "enabled": bool(profile and profile["enabled"]),
                    "sample_count": profile["sample_count"] if profile else 0,
                    "updated_at": profile["updated_at"] if profile else None,
                },
            }
        )

    async def post(self) -> None:
        payload = _json_payload(self)
        password = str(payload.get("password") or "")
        verified = UserRepository.authenticate(self.current_user["username"], password)
        if not verified or verified["id"] != self.current_user["id"]:
            return self.write_json({"ok": False, "message": "当前密码验证失败"}, 401)
        try:
            frames = decode_frames(payload.get("frames"), minimum=5, maximum=8)
            embedding, evidence = FaceVerifier.extract_profile(frames)
        except BiometricError as exc:
            return self.write_json({"ok": False, "message": str(exc)}, 422)
        BiometricRepository.save_face_profile(
            self.current_user["id"], dumps_embedding(embedding), len(frames)
        )
        self.write_json({"ok": True, "message": "人脸档案已安全更新", "evidence": evidence})

    def delete(self) -> None:
        removed = BiometricRepository.delete_face_profile(self.current_user["id"])
        self.write_json(
            {"ok": True, "message": "人脸档案已删除" if removed else "当前没有人脸档案"}
        )


class GestureRecognizeHandler(UserJsonHandler):
    ACTIONS = {
        "victory": {"action": "weather", "employee_code": "weather", "prompt": "@天气 查询成都今天的天气", "label": "天气查询"},
        "fist": {"action": "music", "employee_code": "music", "prompt": "@音乐 推荐一首适合工作时听的音乐", "label": "音乐推荐"},
        "open_palm": {"action": "news", "employee_code": "news", "prompt": "@新闻 汇总今天值得关注的新闻", "label": "新闻简报"},
    }

    async def post(self) -> None:
        payload = _json_payload(self)
        try:
            frames = decode_frames(payload.get("frames"), minimum=3, maximum=7)
            result = GestureRecognizer.recognize(frames)
        except BiometricError as exc:
            return self.write_json({"ok": False, "message": str(exc)}, 422)
        action = self.ACTIONS[result["gesture"]]
        employee = DigitalEmployeeRepository.get_by_code(action["employee_code"])
        triggered = BiometricRepository.log_gesture(
            self.current_user["id"], result["gesture"], action["action"], result["confidence"]
        )
        if not triggered:
            return self.write_json(
                {"ok": False, "message": "相同手势仍在 5 秒冷却中，请稍后再试"}, 429
            )
        self.write_json(
            {
                "ok": True,
                **result,
                **action,
                "employee_id": employee["id"] if employee and employee["enabled"] else None,
                "cooldown_seconds": 5,
            }
        )


class AdminFaceSettingHandler(AdminJsonHandler):
    required_feature = "user_management"

    def post(self) -> None:
        if not self.current_user["is_superadmin"]:
            raise tornado.web.HTTPError(403, reason="仅超级管理员可以调整人脸登录")
        payload = _json_payload(self)
        action = str(payload.get("action") or "")
        enabled = bool(payload.get("enabled"))
        if action == "global":
            BiometricRepository.set_face_login_enabled(enabled, self.current_user["id"])
            return self.write_json({"ok": True, "message": "人脸登录全局开关已更新"})
        if action == "user":
            try:
                user_id = int(payload.get("user_id"))
            except (TypeError, ValueError) as exc:
                raise tornado.web.HTTPError(400, reason="用户编号不正确") from exc
            if not BiometricRepository.toggle_user_face(user_id, enabled):
                raise tornado.web.HTTPError(404, reason="该用户尚未录入人脸")
            return self.write_json({"ok": True, "message": "用户人脸登录状态已更新"})
        raise tornado.web.HTTPError(400, reason="不支持的人脸设置操作")
