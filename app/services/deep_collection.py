"""基于 Crawl4AI 的公开网页深度采集与任务编排。"""

from __future__ import annotations

import importlib
import json
import logging
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from tornado.httpclient import AsyncHTTPClient, HTTPRequest

from app.models.deep_collection import DeepCollectionRepository
from app.models.digital_employee import DigitalEmployeeRepository
from app.models.warehouse import WarehouseRepository
from app.services.collector import CollectionError, _validate_public_url
from app.services.opinion import OpinionSecurityService

LOGGER = logging.getLogger("collection")

_crawl4ai_imported = False
AsyncWebCrawler = None
BrowserConfig = None
CacheMode = None
CrawlerRunConfig = None
CRAWL4AI_VERSION = None


def _import_crawl4ai():
    global _crawl4ai_imported, AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig, CRAWL4AI_VERSION
    if not _crawl4ai_imported:
        crawl4ai = importlib.import_module("crawl4ai")
        # 允许专项测试或部署适配器预先注入单个组件；只补齐未设置项。
        AsyncWebCrawler = AsyncWebCrawler or crawl4ai.AsyncWebCrawler
        BrowserConfig = BrowserConfig or crawl4ai.BrowserConfig
        CacheMode = CacheMode or crawl4ai.CacheMode
        CrawlerRunConfig = CrawlerRunConfig or crawl4ai.CrawlerRunConfig
        CRAWL4AI_VERSION = crawl4ai.__version__
        _crawl4ai_imported = True


class DeepCollectionService:
    @staticmethod
    def collector_employee() -> dict:
        employee = DigitalEmployeeRepository.get_by_code("collection_specialist")
        if not employee or not employee.get("enabled") or not employee.get("crawl4ai_enabled"):
            raise CollectionError("采集专员未配置、已停用或未启用 Crawl4AI 网页采集能力")
        return employee

    @staticmethod
    async def _fetch(url: str) -> tuple[str, str, dict]:
        """调用 Crawl4AI 浏览器提取标题、正文 Markdown 与来源元数据。"""
        _import_crawl4ai()
        await _validate_public_url(url)
        browser_config = BrowserConfig(
            headless=True,
            browser_type="chromium",
            viewport_width=1280,
            viewport_height=800,
            text_mode=True,
            light_mode=True,
            verbose=False,
        )
        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=5,
            excluded_tags=["nav", "footer", "form", "script", "style", "noscript"],
            remove_forms=True,
            remove_overlay_elements=True,
            wait_until="domcontentloaded",
            page_timeout=30000,
            exclude_all_images=True,
            verbose=False,
        )
        try:
            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url=url, config=run_config)
        except Exception as exc:
            LOGGER.exception("crawl4ai request failed", extra={"event": "deep_collection_request_failed"})
            raise CollectionError(f"Crawl4AI 启动或网页访问失败：{str(exc)[:180]}") from exc
        if not result or not result.success:
            message = getattr(result, "error_message", "") if result else "未返回采集结果"
            LOGGER.warning(
                "crawl4ai returned no article body; trying lightweight extractor",
                extra={"event": "deep_collection_fallback", "reason": str(message)[:220]},
            )
            return await DeepCollectionService._fetch_fallback(url, str(message))

        markdown = result.markdown
        content = str(getattr(markdown, "fit_markdown", "") or markdown or "").strip()
        content = re.sub(r"\n{4,}", "\n\n\n", content)[:200000]
        if len(content) < 80:
            return await DeepCollectionService._fetch_fallback(
                url, "Crawl4AI 返回的可见正文不足 80 字"
            )
        metadata_source = result.metadata if isinstance(result.metadata, dict) else {}
        title = str(metadata_source.get("title") or "").strip()[:500]
        links = result.links if isinstance(result.links, dict) else {}
        metadata = {
            "url": url,
            "final_url": str(getattr(result, "redirected_url", "") or result.url or url),
            "http_status": int(result.status_code or 0),
            "parser": "crawl4ai",
            "crawl4ai_version": str(CRAWL4AI_VERSION),
            "content_format": "markdown",
            "content_chars": len(content),
            "internal_links": len(links.get("internal", [])),
            "external_links": len(links.get("external", [])),
        }
        return title, content, metadata

    @staticmethod
    async def _fetch_fallback(url: str, crawl4ai_reason: str = "") -> tuple[str, str, dict]:
        """用公开 HTML、JSON-LD 和常见正文容器补救浏览器提取失败。"""
        current_url = url
        response = None
        for _ in range(4):
            await _validate_public_url(current_url)
            response = await AsyncHTTPClient().fetch(
                HTTPRequest(
                    current_url,
                    method="GET",
                    headers={
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.7",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 Chrome/138 Safari/537.36"
                        ),
                    },
                    connect_timeout=10,
                    request_timeout=25,
                    follow_redirects=False,
                    decompress_response=True,
                ),
                raise_error=False,
            )
            if response.code in {301, 302, 303, 307, 308}:
                target = response.headers.get("Location", "")
                if not target:
                    break
                current_url = urljoin(current_url, target)
                continue
            break
        if response is None or response.code != 200:
            code = response.code if response is not None else 0
            raise CollectionError(f"正文补全失败：来源返回 HTTP {code}")
        if len(response.body or b"") > 3 * 1024 * 1024:
            raise CollectionError("正文补全失败：来源页面超过 3 MB 限制")

        html = response.body.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        title = ""
        candidates: list[str] = []
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                payload = json.loads(script.string or script.get_text() or "{}")
            except json.JSONDecodeError:
                continue
            queue = payload if isinstance(payload, list) else [payload]
            for entry in queue:
                if isinstance(entry, dict) and isinstance(entry.get("@graph"), list):
                    queue.extend(entry["@graph"])
                if not isinstance(entry, dict):
                    continue
                title = title or str(entry.get("headline") or entry.get("name") or "").strip()
                body = str(entry.get("articleBody") or entry.get("text") or "").strip()
                if body:
                    candidates.append(body)

        title = title or str((soup.title.string if soup.title and soup.title.string else "")).strip()
        selectors = (
            "article", '[itemprop="articleBody"]', "main", ".article-content",
            ".article-body", ".post-content", ".entry-content", "#article-content",
        )
        for selector in selectors:
            for element in soup.select(selector)[:4]:
                text = "\n".join(
                    part.strip() for part in element.stripped_strings if part.strip()
                )
                if text:
                    candidates.append(text)
        content = max(candidates, key=len, default="")
        content = re.sub(r"\n{3,}", "\n\n", content).strip()[:200000]
        if len(content) < 80:
            domain = (urlsplit(current_url).hostname or "该来源").removeprefix("www.")
            hint = (
                "该聚合页启用了内容保护，请换用新闻的原始媒体链接后再补全正文"
                if domain.endswith(("msn.com", "msn.cn"))
                else "页面只返回脚本空壳，请换用可公开阅读的原文链接"
            )
            raise CollectionError(f"正文补全失败：{domain} 未提供可提取正文；{hint}")
        return title[:500], content, {
            "url": url,
            "final_url": current_url,
            "http_status": int(response.code),
            "parser": "beautifulsoup-fallback",
            "content_format": "text",
            "content_chars": len(content),
            "crawl4ai_reason": crawl4ai_reason[:500],
        }

    @staticmethod
    async def run(task_id: int) -> None:
        try:
            employee = DeepCollectionService.collector_employee()
            detail = DeepCollectionRepository.detail(task_id)
            if not detail:
                return
            item = WarehouseRepository.get(int(detail["warehouse_item_id"]))
            if not item:
                raise CollectionError("待采集的仓库数据不存在")
            DeepCollectionRepository.update_progress(task_id, 12, "接收任务", f"@{employee['mention']} 已接收任务")
            DeepCollectionRepository.update_progress(task_id, 28, "校验来源", "正在校验公开网页地址与网络边界")
            DeepCollectionRepository.update_progress(task_id, 45, "获取公开原文", f"正在读取并识别网页正文：{item['url']}")
            title, content, metadata = await DeepCollectionService._fetch(item["url"])
            DeepCollectionRepository.update_progress(task_id, 72, "解析详细数据", f"已提取标题与 {len(content)} 个正文字符")
            DeepCollectionRepository.update_progress(task_id, 88, "写入数据仓库", "正在持久化正文、来源和任务日志")
            metadata["employee_code"] = employee["code"]
            metadata["employee_mention"] = "@" + employee["mention"]
            metadata["update_collection"] = bool(detail.get("is_update"))
            DeepCollectionRepository.complete(
                task_id, title or item["title"], content,
                content[:500], metadata,
            )
            security = OpinionSecurityService.analyze_and_record(
                "collection",
                item["id"],
                f"{title or item['title']}\n{content}",
                detail.get("created_by"),
                {"stage": "deep_collection", "task_id": task_id},
            )
            risk = {"medium": "high", "high": "high", "critical": "critical", "low": "low"}.get(
                security["risk_level"], "normal"
            )
            WarehouseRepository.update_risk_level(item["id"], risk, security)
            WarehouseRepository.update_keywords(
                item["id"],
                ",".join(word["word"] for word in security["matched_words"]),
                str(security["matched_words"]),
            )
        except Exception as exc:
            LOGGER.exception("deep collection task failed", extra={"task_id": task_id, "event": "deep_collection_task_failed"})
            DeepCollectionRepository.fail(task_id, str(exc) or "深度采集失败")
