"""接口管理与测试接口。"""

from __future__ import annotations

import json
import logging
import time
from urllib.parse import urlsplit

from tornado.httpclient import HTTPRequest

from app.core.net_guard import guarded_fetch

from app.controllers.base import AdminBaseHandler, AdminJsonHandler
from app.models.interface import (
    InterfaceCallRepository,
    InterfaceRepository,
    assert_public_url,
)

LOGGER = logging.getLogger("interface")


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


class AdminInterfacesHandler(AdminBaseHandler):
    required_feature = "interface_management"

    def get(self):
        keyword = self.get_query_argument("q", "").strip()
        status = self.get_query_argument("status", "").strip()
        page = _page(self)
        interfaces, total = InterfaceRepository.list(
            keyword=keyword,
            status=status,
            page=page,
            page_size=10,
        )
        for interface in interfaces:
            interface["headers_json"] = json.dumps(
                interface.get("request_headers", {}), ensure_ascii=False, indent=2
            )
            interface["params_json"] = json.dumps(
                interface.get("request_params", {}), ensure_ascii=False, indent=2
            )
            interface["call_count"] = int(interface.get("call_count", 0))
            interface["success_count"] = int(interface.get("success_count", 0))
            interface["success_rate"] = (
                round(interface["success_count"] / interface["call_count"] * 100, 1)
                if interface["call_count"] > 0
                else 0
            )
        self.render_admin(
            "admin/interfaces.html",
            title="接口管理 · 零界",
            active_menu="interface_management",
            interfaces=interfaces,
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
                interface_id = _integer(self, "interface_id", 0) if action == "update" else None
                code = self.get_body_argument("code", "").strip()
                name = self.get_body_argument("name", "").strip()
                api_url = self.get_body_argument("api_url", "").strip()
                request_method = self.get_body_argument("request_method", "GET").strip().upper()
                timeout_seconds = _integer(self, "timeout_seconds", 15)
                retry_count = _integer(self, "retry_count", 0)
                response_path = self.get_body_argument("response_path", "").strip()
                description = self.get_body_argument("description", "").strip()[:500]
                enabled = self.get_body_argument("enabled", "1") == "1"

                if not 2 <= len(name) <= 60:
                    raise ValueError("接口名称需为 2—60 个字符")
                if request_method not in {"GET", "POST"}:
                    raise ValueError("请求方法仅支持 GET 和 POST")
                if not 3 <= timeout_seconds <= 60:
                    raise ValueError("超时时间需为 3—60 秒")
                if not 0 <= retry_count <= 5:
                    raise ValueError("重试次数需为 0—5")

                values = dict(
                    code=code,
                    name=name,
                    api_url=api_url,
                    request_method=request_method,
                    request_headers=self.get_body_argument("request_headers", "{}"),
                    request_params=self.get_body_argument("request_params", "{}"),
                    response_path=response_path,
                    timeout_seconds=timeout_seconds,
                    retry_count=retry_count,
                    description=description,
                    enabled=enabled,
                )

                if interface_id:
                    result = InterfaceRepository.update(interface_id=interface_id, **values)
                    message, level = _operation_message(result, "接口配置已更新")
                else:
                    result = InterfaceRepository.create(
                        created_by=self.current_user["id"], **values
                    )
                    message, level = _operation_message(result, "接口创建成功")
                return self.redirect_with_message("/admin/interfaces", message, level)

            interface_id = _integer(self, "interface_id", 0)
            if action == "delete":
                result = InterfaceRepository.delete(interface_id)
                message, level = _operation_message(result, "接口已删除")
            elif action == "toggle":
                result = InterfaceRepository.toggle(interface_id)
                message, level = _operation_message(result, "接口状态已更新")
            else:
                raise ValueError("未知操作")
            self.redirect_with_message("/admin/interfaces", message, level)
        except ValueError as exc:
            self.redirect_with_message("/admin/interfaces", str(exc), "error")


class AdminInterfaceTestHandler(AdminJsonHandler):
    required_feature = "interface_management"

    async def post(self):
        payload = self.json_body()
        try:
            interface_id = int(payload.get("interface_id") or 0)
            # 限制测试输入长度，缩小其对被替换 URL/参数/请求头的操纵面。
            test_input = str(payload.get("input", "") or "")[:2000]
        except (TypeError, ValueError) as exc:
            return self.write_json({"ok": False, "message": str(exc)}, 400)

        interface = InterfaceRepository.get(interface_id)
        if not interface or not interface.get("enabled"):
            return self.write_json({"ok": False, "message": "接口不存在或已停用"}, 404)

        url = str(interface["api_url"])
        if "{{input}}" in url:
            url = url.replace("{{input}}", test_input)

        params = interface.get("request_params", {})
        if isinstance(params, dict):
            params = {k: (str(v).replace("{{input}}", test_input) if isinstance(v, str) else v) for k, v in params.items()}

        headers = {"Accept": "application/json", "User-Agent": "DataFinderAgentOS/0.3"}
        request_headers = interface.get("request_headers", {})
        if isinstance(request_headers, dict):
            for key, value in request_headers.items():
                lowered = str(key).lower()
                if lowered not in {"cookie", "authorization", "proxy-authorization", "host", "content-length"}:
                    headers[str(key)] = str(value).replace("{{input}}", test_input)[:1000]

        method = interface["request_method"]
        body = None
        if method == "GET":
            from urllib.parse import parse_qsl, urlencode
            parsed = urlsplit(url)
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query.update({str(k): str(v) for k, v in params.items()})
            url = urlsplit(url)._replace(query=urlencode(query)).geturl()
        else:
            headers["Content-Type"] = "application/json"
            body = json.dumps(params, ensure_ascii=False).encode("utf-8")

        chunks = bytearray()

        # 占位符替换后重新校验最终 URL，拒绝解析到内网/环回地址的目标（SSRF 防御）。
        try:
            assert_public_url(url)
        except ValueError as exc:
            return self.write_json({"ok": False, "message": str(exc)}, 400)

        def receive(chunk: bytes) -> None:
            if len(chunks) + len(chunk) > 2 * 1024 * 1024:
                raise ValueError("接口响应超过 2MB 安全限制")
            chunks.extend(chunk)

        started = time.monotonic()
        try:
            response = await guarded_fetch(
                HTTPRequest(
                    url=url,
                    method=method,
                    headers=headers,
                    body=body,
                    connect_timeout=10,
                    request_timeout=interface["timeout_seconds"],
                    follow_redirects=False,
                    streaming_callback=receive,
                ),
                raise_error=False,
            )
        except ValueError:
            raise
        except Exception as exc:
            InterfaceCallRepository.record(
                interface_id=interface_id,
                user_id=self.current_user["id"],
                status_code=0,
                success=False,
                error_message=str(exc)[:500],
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            return self.write_json({"ok": False, "message": "接口连接失败或超时"}, 500)

        latency_ms = int((time.monotonic() - started) * 1000)

        if response.code != 200:
            InterfaceCallRepository.record(
                interface_id=interface_id,
                user_id=self.current_user["id"],
                status_code=response.code,
                success=False,
                error_message=f"HTTP {response.code}",
                latency_ms=latency_ms,
            )
            return self.write_json({"ok": False, "message": f"接口返回 HTTP {response.code}"}, response.code)

        try:
            data = json.loads(bytes(chunks).decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            InterfaceCallRepository.record(
                interface_id=interface_id,
                user_id=self.current_user["id"],
                status_code=response.code,
                success=False,
                error_message="接口未返回有效 JSON",
                latency_ms=latency_ms,
            )
            return self.write_json({"ok": False, "message": "接口未返回有效 JSON"}, 400)

        InterfaceCallRepository.record(
            interface_id=interface_id,
            user_id=self.current_user["id"],
            status_code=response.code,
            success=True,
            latency_ms=latency_ms,
        )

        response_path = interface.get("response_path")
        if response_path:
            try:
                for part in response_path.split("."):
                    if part:
                        data = data[part]
            except (KeyError, TypeError):
                return self.write_json({"ok": False, "message": f"响应路径 {response_path} 不存在"}, 400)

        return self.write_json({"ok": True, "data": data, "latency_ms": latency_ms})


class AdminInterfaceLogsHandler(AdminBaseHandler):
    required_feature = "interface_management"

    def get(self, interface_id: str):
        try:
            interface_id_int = int(interface_id)
        except ValueError:
            return self.redirect_with_message("/admin/interfaces", "接口编号不正确", "error")

        interface = InterfaceRepository.get(interface_id_int)
        if not interface:
            return self.redirect_with_message("/admin/interfaces", "接口不存在", "error")

        page = _page(self)
        logs, total = InterfaceCallRepository.list(
            interface_id=interface_id_int,
            page=page,
            page_size=20,
        )

        for log in logs:
            log["success"] = bool(log.get("success"))

        self.render_admin(
            "admin/interface_logs.html",
            title=f"接口调用日志 · {interface['name']}",
            active_menu="interface_management",
            interface=interface,
            logs=logs,
            page=page,
            pages=max(1, (total + 19) // 20),
            total=total,
            can_write=False,
        )