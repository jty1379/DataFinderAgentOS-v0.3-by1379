"""Safe intent routing for warehouse questions and report requests."""

from __future__ import annotations

import re

from app.models.analytics import AnalyticsRepository


class UnsafeQueryError(ValueError):
    """Raised when a request attempts SQL or prompt-injection control."""


class QueryIntentService:
    _SQL_PATTERN = re.compile(
        r"(?:(?:select|insert|update|delete|drop|alter|pragma|attach|detach|union)|;|--|/\*)",
        re.IGNORECASE,
    )
    _INJECTION_TERMS = (
        "忽略之前", "忽略以上", "系统提示词", "泄露提示词", "显示提示词",
        "越权", "绕过权限", "扮演管理员", "开发者指令", "prompt injection",
    )

    @classmethod
    def validate(cls, text: str) -> None:
        text = str(text or "").strip()
        if cls._SQL_PATTERN.search(text) or any(term.lower() in text.lower() for term in cls._INJECTION_TERMS):
            raise UnsafeQueryError(
                "该请求包含 SQL 或越权指令，已被安全策略拒绝。请改用自然语言描述统计目标，例如“统计数据仓库来源分布”。"
            )

    @classmethod
    def analyze(cls, text: str) -> dict | None:
        text = str(text or "").strip()
        cls.validate(text)
        if any(term in text for term in ("报告", "简报", "研判")):
            return cls._report()
        if any(term in text for term in ("知识图谱", "图谱", "关联关系", "来源关联", "关系挖掘")):
            return cls._graph()
        if any(term in text for term in ("趋势", "近七日", "最近七天", "变化")):
            return cls._trend()
        if any(term in text for term in ("来源分布", "数据源分布", "来源统计")):
            return cls._sources()
        if any(term in text for term in ("深度采集", "深采")):
            return cls._deep()
        if any(term in text for term in ("统计", "总数", "概览", "数据仓库", "采集数据", "数据分析")):
            return cls._overview()
        return None

    @staticmethod
    def _base(intent: str, title: str, narrative: str, visualizations: list[dict]) -> dict:
        return {
            "mode": "card",
            "employee": "问数分析器",
            "data": {
                "kind": "analysis",
                "intent": intent,
                "title": title,
                "narrative": narrative,
                "visualizations": visualizations,
                "safe_query": True,
                "source_note": "结果来自系统数据仓库的只读固定统计，未执行用户 SQL。",
            },
        }

    @classmethod
    def _overview(cls) -> dict:
        data = AnalyticsRepository.overview()
        narrative = (
            f"当前仓库共有 {data['warehouse_count']} 条数据，其中 {data['deep_count']} 条已完成深度采集；"
            f"已启用 {data['source_count']} 个数据源，累计采集结果 {data['collected_count']} 条。"
        )
        values = [
            {"label": "仓库数据", "value": data["warehouse_count"]},
            {"label": "深度采集", "value": data["deep_count"]},
            {"label": "启用数据源", "value": data["source_count"]},
            {"label": "成功任务", "value": data["successful_runs"]},
        ]
        return cls._base("overview", "数据仓库概览", narrative, [{"type": "kpi", "title": "核心指标", "data": values}])

    @classmethod
    def _sources(cls) -> dict:
        rows = AnalyticsRepository.source_distribution()
        total = sum(item["value"] for item in rows)
        lead = rows[0]["label"] if rows else "暂无数据"
        return cls._base(
            "source_distribution", "数据来源分布",
            f"已按数据来源汇总 {total} 条仓库记录，当前数量最多的来源为“{lead}”。",
            [{"type": "bar", "title": "来源数据量", "data": rows}],
        )

    @classmethod
    def _trend(cls) -> dict:
        rows = AnalyticsRepository.daily_trend(7)
        total = sum(item["value"] for item in rows)
        return cls._base(
            "trend", "近七日入仓趋势", f"近七日共有 {total} 条数据进入仓库，折线按入仓日期汇总。",
            [{"type": "line", "title": "每日入仓量", "data": rows}],
        )

    @classmethod
    def _deep(cls) -> dict:
        rows = AnalyticsRepository.deep_status()
        return cls._base(
            "deep_collection", "深度采集进度",
            f"已完成 {rows[0]['value']} 条，仍有 {rows[1]['value']} 条待深度采集。",
            [{"type": "donut", "title": "深度采集状态", "data": rows}],
        )

    @classmethod
    def _graph(cls) -> dict:
        graph = AnalyticsRepository.relationship_graph()
        return cls._base(
            "knowledge_graph", "来源—数据关系图谱",
            f"从最近入仓数据中识别出 {len(graph['nodes'])} 个节点、{len(graph['edges'])} 条采集关系。",
            [{"type": "graph", "title": "来源与数据条目关系", **graph}],
        )

    @classmethod
    def _report(cls) -> dict:
        overview = AnalyticsRepository.overview()
        sources = AnalyticsRepository.source_distribution(6)
        trend = AnalyticsRepository.daily_trend(7)
        recent = AnalyticsRepository.recent_items(6)
        narrative = (
            f"本次报告基于 {overview['warehouse_count']} 条仓库数据生成。"
            f"其中 {overview['deep_count']} 条已深度采集，近七日新增 {sum(x['value'] for x in trend)} 条。"
        )
        table = [
            {
                "title": item["title"], "source": item["source"],
                "deep": "是" if item["deep_collected"] else "否",
            }
            for item in recent
        ]
        return cls._base(
            "report", "数据仓库分析简报", narrative,
            [
                {"type": "bar", "title": "来源分布", "data": sources},
                {"type": "line", "title": "近七日趋势", "data": trend},
                {"type": "table", "title": "最近入仓数据", "columns": ["title", "source", "deep"], "labels": ["标题", "来源", "深采"], "data": table},
            ],
        )
