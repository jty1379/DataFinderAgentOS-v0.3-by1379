"""出站 HTTP 的统一 SSRF 防护工具。

集中提供两类能力，供全项目所有对外请求复用，避免"某个模块漏了校验"：

1. ``assert_public_url``  —— 同步、配置期使用。校验协议 / 凭据，并对主机名做
   尽力而为的 DNS 解析检查（解析失败不阻断保存，避免误伤临时不可达的公网地址）。
2. ``guarded_fetch``      —— 异步、请求期使用。**解析一次 DNS 并固定该 IP**，
   把固定后的 IP 交给本次请求的专用 HTTP 客户端，从根源消除 DNS 重绑定
   （TOCTOU）：校验时与连接时使用的是同一个 IP，攻击者无法在两次解析之间
   把域名重新绑定到内网地址。URL 中仍保留原始主机名，因此 HTTPS 的 SNI 与
   证书校验不受影响。
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from tornado.httpclient import AsyncHTTPClient, HTTPRequest
from tornado.netutil import Resolver

# 常见的云元数据 / 内网别名主机，即便解析结果为公网也一律拒绝。
BLOCKED_HOSTS = {
    "metadata",
    "metadata.google.internal",
    "instance-data",
}

_RESOLVE_TIMEOUT = 5


class PublicUrlError(ValueError):
    """URL 未通过公网安全校验，可安全展示给调用方。"""


def is_public_ip(address: str) -> bool:
    """判断字符串 IP 是否为公网可路由地址。

    ``is_global`` 会同时拒绝私网、回环、链路本地、保留、多播、CGNAT 以及
    云元数据常用的 ``169.254.0.0/16`` 等非公网范围。
    """
    try:
        return bool(ipaddress.ip_address(address).is_global)
    except ValueError:
        return False


def _check_scheme_and_credentials(url: str):
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise PublicUrlError("目标地址仅支持完整的 http/https URL")
    if parsed.username or parsed.password:
        raise PublicUrlError("目标地址不允许携带用户凭据")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in BLOCKED_HOSTS or hostname.endswith(".internal"):
        raise PublicUrlError("目标地址指向受限主机")
    port = parsed.port or (443 if scheme == "https" else 80)
    return parsed, hostname, port


def assert_public_url(url: str) -> None:
    """配置期同步校验：拒绝明显指向内网/环回/链路本地的 URL。

    对 IP 字面量直接判定；对域名做尽力而为的解析检查——解析失败时不阻断
    （避免临时 DNS 故障导致合法公网地址无法保存），真正的 fail-closed 交由
    请求期的 :func:`guarded_fetch` 兜底。
    """
    _, hostname, _ = _check_scheme_and_credentials(url)
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise PublicUrlError("目标地址不允许指向内网、回环或链路本地地址")
        return
    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        resolved = []
    for info in resolved:
        if not is_public_ip(info[4][0].split("%")[0]):
            raise PublicUrlError("目标地址解析到内网或受限网络地址，已被拒绝")


class _PinnedResolver(Resolver):
    """只返回预先校验并固定的 IP 列表，供单次请求的专用客户端使用。"""

    def initialize(self, addresses):  # noqa: D401 - Tornado Configurable 约定
        # addresses: list[tuple[int, str]] -> (address_family, ip)
        self._addresses = list(addresses)

    async def resolve(self, host, port, family=socket.AF_UNSPEC):
        matched = [
            (fam, ip)
            for fam, ip in self._addresses
            if family in (socket.AF_UNSPEC, fam)
        ]
        if not matched:
            matched = list(self._addresses)
        results = []
        for fam, ip in matched:
            if fam == socket.AF_INET6:
                results.append((fam, (ip, port, 0, 0)))
            else:
                results.append((fam, (ip, port)))
        return results


async def _resolve_public_addresses(hostname: str, port: int) -> list[tuple[int, str]]:
    """解析主机名并要求所有结果均为公网地址，返回固定用的 (family, ip) 列表。"""
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise PublicUrlError("不允许访问私网、回环或链路本地地址")
        family = socket.AF_INET6 if literal.version == 6 else socket.AF_INET
        return [(family, str(literal))]
    try:
        records = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, hostname, port, 0, socket.SOCK_STREAM),
            timeout=_RESOLVE_TIMEOUT,
        )
    except (OSError, TimeoutError) as exc:
        raise PublicUrlError("目标域名无法解析") from exc
    addresses: list[tuple[int, str]] = []
    seen: set[str] = set()
    for record in records:
        ip = record[4][0].split("%")[0]
        if ip in seen:
            continue
        seen.add(ip)
        if not is_public_ip(ip):
            raise PublicUrlError("目标域名解析到内网或受限网络地址")
        addresses.append((record[0], ip))
    if not addresses:
        raise PublicUrlError("目标域名解析结果为空")
    return addresses


async def guarded_fetch(request: HTTPRequest, **kwargs):
    """带 SSRF 防护与 DNS 固定的 ``AsyncHTTPClient.fetch`` 替代品。

    在建立连接前解析一次 DNS，确认所有解析结果均为公网地址，并把这些 IP
    固定给本次请求使用的专用客户端，杜绝校验与连接之间的 DNS 重绑定窗口。
    """
    url = request.url if isinstance(request, HTTPRequest) else str(request)
    _, hostname, port = _check_scheme_and_credentials(url)
    addresses = await _resolve_public_addresses(hostname, port)
    resolver = _PinnedResolver(addresses=addresses)
    client = AsyncHTTPClient(force_instance=True, resolver=resolver)
    try:
        return await client.fetch(request, **kwargs)
    finally:
        client.close()
