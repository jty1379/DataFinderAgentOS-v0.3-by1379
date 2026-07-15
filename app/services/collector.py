"""安全的公开网页采集服务。"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from tornado.httpclient import AsyncHTTPClient, HTTPRequest


class CollectionError(ValueError):
    """可展示给管理员的采集错误。"""


ALLOWED_HEADERS = {
    "accept",
    "accept-language",
    "cache-control",
    "pragma",
    "referer",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "sec-fetch-user",
    "upgrade-insecure-requests",
    "user-agent",
}
FORBIDDEN_HEADERS = {
    "authorization",
    "cookie",
    "host",
    "connection",
    "content-length",
    "proxy-authorization",
    "proxy-connection",
}
BLOCKED_HOSTS = {
    "metadata",
    "metadata.google.internal",
    "instance-data",
}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 15


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.h3_depth = 0
        self.current: dict | None = None
        self.pending_metadata: dict = {}
        self.primary: list[dict] = []
        self.fallback: list[dict] = []

    def handle_comment(self, data: str) -> None:
        if not data.startswith("s-data:"):
            return
        try:
            payload = json.loads(data[len("s-data:") :])
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        self.pending_metadata = {
            "summary": str(payload.get("summary") or "").strip()[:2000],
            "source_name": str(payload.get("sourceName") or "").strip()[:100],
            "published_at": str(
                payload.get("publishedAt")
                or payload.get("publishTime")
                or payload.get("date")
                or ""
            ).strip()[:100],
        }

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "h3":
            self.h3_depth += 1
        if tag != "a" or self.current is not None:
            return
        attributes = {str(key).lower(): value for key, value in attrs}
        href = str(attributes.get("href") or "").strip()
        if not href:
            return
        self.current = {
            "href": urljoin(self.base_url, href),
            "text": [],
            "primary": self.h3_depth > 0,
            "target": str(attributes.get("target") or ""),
            "metadata": dict(self.pending_metadata) if self.h3_depth > 0 else {},
        }

    def handle_data(self, data: str) -> None:
        if self.current:
            self.current["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self.current:
            title = " ".join("".join(self.current["text"]).split())
            url = self.current["href"]
            parsed = urlsplit(url)
            if (
                len(title) >= 4
                and parsed.scheme.lower() in {"http", "https"}
                and parsed.hostname
            ):
                result = {
                    "title": title[:300],
                    "url": url[:2000],
                    **self.current.get("metadata", {}),
                }
                if self.current["primary"]:
                    self.primary.append(result)
                elif self.current["target"].lower() == "_blank":
                    self.fallback.append(result)
            self.current = None
            self.pending_metadata = {}
        if tag == "h3" and self.h3_depth:
            self.h3_depth -= 1

    def results(self, limit: int) -> list[dict]:
        selected = self.primary or self.fallback
        output: list[dict] = []
        seen: set[str] = set()
        for item in selected:
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            output.append(item)
            if len(output) >= limit:
                break
        return output


def _sanitized_headers(*groups) -> dict[str, str]:
    output: dict[str, str] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        for raw_name, raw_value in group.items():
            name = str(raw_name).strip()
            lowered = name.lower()
            if lowered in FORBIDDEN_HEADERS:
                raise CollectionError(f"请求头 {name} 不允许用于采集")
            if lowered not in ALLOWED_HEADERS:
                continue
            value = str(raw_value).strip()
            if "\r" in value or "\n" in value:
                raise CollectionError("请求头不允许包含换行符")
            output[name] = value[:1000]
    output.setdefault(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    )
    output.setdefault("Accept", "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8")
    return output


def _public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    # is_global 同时拒绝私网、回环、链路本地、保留、CGNAT 与
    # 云元数据常用的非公网地址。
    return bool(ip.is_global)


async def _validate_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise CollectionError("瞭源地址仅支持 http/https")
    if parsed.username or parsed.password:
        raise CollectionError("瞭源地址不允许携带用户凭据")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in BLOCKED_HOSTS or hostname.endswith(".internal"):
        raise CollectionError("瞭源地址指向受限主机")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if not _public_ip(str(literal)):
            raise CollectionError("不允许采集私网、回环或链路本地地址")
        return
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        records = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, hostname, port, 0, socket.SOCK_STREAM),
            timeout=5,
        )
    except (OSError, asyncio.TimeoutError) as exc:
        raise CollectionError("瞭源域名无法解析") from exc
    addresses = {record[4][0].split("%")[0] for record in records}
    if not addresses or any(not _public_ip(address) for address in addresses):
        raise CollectionError("瞭源域名解析到受限网络地址")


def _request_url(rule: dict, keyword: str, page: int) -> str:
    base_url = str(rule.get("base_url") or "").strip()
    parsed = urlsplit(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    fixed_params = rule.get("fixed_params") or {}
    if isinstance(fixed_params, dict):
        for key, value in fixed_params.items():
            if isinstance(value, (str, int, float, bool)):
                query[str(key)] = str(value)
    keyword_param = str(rule.get("keyword_param") or "word")
    query[keyword_param] = keyword
    page_param = str(rule.get("page_param") or "").strip()
    if page_param:
        page_start = max(0, int(rule.get("page_start") or 0))
        page_step = max(1, int(rule.get("page_step") or 10))
        query[page_param] = str(page_start + (max(1, page) - 1) * page_step)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", urlencode(query), ""))


class CollectorService:
    @staticmethod
    async def collect(
        rule: dict, keyword: str, page: int = 1, page_size: int = 12
    ) -> list[dict]:
        keyword = keyword.strip()
        if not 1 <= len(keyword) <= 100:
            raise CollectionError("采集关键词需为 1—100 个字符")
        if not rule.get("enabled", True) or not rule.get("source_enabled", True):
            raise CollectionError("采集规则或所属瞭源已停用")
        page = max(1, int(page or 1))
        page_size = min(100, max(1, int(page_size or rule.get("page_size") or 12)))
        url = _request_url(rule, keyword, page)
        await _validate_public_url(url)
        headers = _sanitized_headers(
            rule.get("default_headers"), rule.get("request_headers")
        )
        chunks = bytearray()

        def receive_chunk(chunk: bytes) -> None:
            if len(chunks) + len(chunk) > MAX_RESPONSE_BYTES:
                raise CollectionError("外部瞭源响应超过 2MB 安全限制")
            chunks.extend(chunk)

        request = HTTPRequest(
            url=url,
            method="GET",
            headers=headers,
            connect_timeout=min(10, REQUEST_TIMEOUT_SECONDS),
            request_timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=False,
            decompress_response=True,
            streaming_callback=receive_chunk,
        )
        try:
            response = await AsyncHTTPClient().fetch(request, raise_error=False)
        except CollectionError:
            raise
        except Exception as exc:
            raise CollectionError("外部瞭源请求失败或超时") from exc
        if 300 <= response.code < 400:
            location = response.headers.get("Location", "").lower()
            if "wappass" in location or "verify" in location:
                raise CollectionError("外部站点触发安全验证，请稍后重试")
            raise CollectionError("外部瞭源返回重定向，为避免绕过地址校验已拒绝")
        if response.code != 200:
            raise CollectionError(f"外部瞭源返回 HTTP {response.code}")
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type and "html" not in content_type and "text/" not in content_type:
            raise CollectionError("外部瞭源未返回可解析的网页内容")
        body = bytes(chunks)
        charset = "utf-8"
        if "charset=" in content_type:
            charset = content_type.split("charset=", 1)[1].split(";", 1)[0].strip()
        try:
            html = body.decode(charset, errors="replace")
        except LookupError:
            html = body.decode("utf-8", errors="replace")
        lowered_html = html.lower()
        if "wappass" in lowered_html or "百度安全验证" in html:
            raise CollectionError("外部站点触发安全验证，本次未尝试绕过")
        parser = _LinkParser(url)
        try:
            parser.feed(html)
        except Exception as exc:
            raise CollectionError("瞭源页面解析失败") from exc
        source_name = str(rule.get("source_name") or "").strip()
        output: list[dict] = []
        for item in parser.results(page_size):
            output.append(
                {
                    **item,
                    "summary": str(item.get("summary") or "")[:2000],
                    "source_name": str(item.get("source_name") or source_name)[:100],
                    "published_at": str(item.get("published_at") or "")[:100],
                    "raw_data": {
                        "parser": str(rule.get("parser_type") or "generic_links"),
                        "request_url": url,
                    },
                }
            )
        return output
