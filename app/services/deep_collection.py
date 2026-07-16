"""基于 Crawl4AI 的公开网页深度采集与任务编排。"""

from __future__ import annotations

import importlib
import logging
import re

from app.models.deep_collection import DeepCollectionRepository
from app.models.digital_employee import DigitalEmployeeRepository
from app.models.warehouse import WarehouseRepository
from app.services.collector import CollectionError, _validate_public_url

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
        AsyncWebCrawler = crawl4ai.AsyncWebCrawler
        BrowserConfig = crawl4ai.BrowserConfig
        CacheMode = crawl4ai.CacheMode
        CrawlerRunConfig = crawl4ai.CrawlerRunConfig
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
            raise CollectionError(f"Crawl4AI 采集失败：{str(message)[:220]}")

        markdown = result.markdown
        content = str(getattr(markdown, "fit_markdown", "") or markdown or "").strip()
        content = re.sub(r"\n{4,}", "\n\n\n", content)[:200000]
        if len(content) < 20:
            raise CollectionError("Crawl4AI 未提取到足够的标题或正文数据")
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
            DeepCollectionRepository.update_progress(task_id, 45, "Crawl4AI 浏览", f"正在通过 Crawl4AI 访问：{item['url']}")
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
        except Exception as exc:
            LOGGER.exception("deep collection task failed", extra={"task_id": task_id, "event": "deep_collection_task_failed"})
            DeepCollectionRepository.fail(task_id, str(exc) or "深度采集失败")
