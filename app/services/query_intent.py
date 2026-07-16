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
        "越权", "绕过权限", "扮演管理员", "你现在是管理员", "执行删除", "删除操作",
        "开发者指令", "prompt injection",
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
        # 先匹配信息量更高的业务意图，避免“统计、采集、来源”等宽泛词
        # 抢占“失败率、性能、各来源”等明确问法。
        if any(term in text for term in ("失败率", "失败", "出错")):
            return cls._failure_analysis()
        if any(term in text for term in ("耗时", "平均耗时", "性能", "速度", "最慢")):
            return cls._performance_analysis()
        if any(term in text for term in ("高风险", "风险内容", "敏感", "风险等级")):
            return cls._risk_analysis()
        if any(term in text for term in ("关键词", "频率最高", "热词")):
            return cls._keyword_analysis()
        if any(term in text for term in ("各来源", "各个来源", "来源分别")):
            return cls._sources_breakdown()
        if any(term in text for term in ("采集了多少", "今天采集", "采集数量", "采集了")):
            return cls._daily_collection()
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

    @classmethod
    def _daily_collection(cls) -> dict:
        """回答：今天采集了多少条数据？"""
        rows = AnalyticsRepository.daily_trend(1)
        today_count = rows[-1]["value"] if rows else 0

        # 统计近7天数据
        weekly = AnalyticsRepository.daily_trend(7)
        weekly_total = sum(item["value"] for item in weekly)

        narrative = f"今日共采集 {today_count} 条数据，近七日累计采集 {weekly_total} 条。"
        return cls._base(
            "daily_collection", "今日采集统计", narrative,
            [{"type": "kpi", "title": "采集数量", "data": [
                {"label": "今日采集", "value": today_count},
                {"label": "周均采集", "value": round(weekly_total / 7) if weekly_total else 0},
            ]}]
        )

    @classmethod
    def _sources_breakdown(cls) -> dict:
        """回答：各来源分别有多少条新闻？"""
        sources = AnalyticsRepository.source_distribution(12)
        total = sum(item["value"] for item in sources)
        narrative = f"数据源统计显示，已采集 {total} 条数据，分布在 {len(sources)} 个数据源中。"
        return cls._base(
            "sources_breakdown", "各来源数据统计", narrative,
            [{"type": "bar", "title": "来源数据量", "data": sources}]
        )

    @classmethod
    def _failure_analysis(cls) -> dict:
        """回答：哪个来源失败率最高？"""
        performance = AnalyticsRepository.source_performance()
        if not performance:
            narrative = "暂无采集任务数据。"
            return cls._base(
                "failure_analysis", "来源采集失败率", narrative,
                [{"type": "kpi", "title": "采集统计", "data": [{"label": "任务总数", "value": 0}]}]
            )

        # 找失败率最高的
        worst = max(performance, key=lambda x: 100 - x.get("success_rate", 100))
        table = [
            {
                "source": item["label"],
                "success": item["success_count"],
                "total": item["total_count"],
                "rate": f"{item['success_rate']}%"
            }
            for item in sorted(performance, key=lambda x: x.get("success_rate", 0))[:5]
        ]
        narrative = f"数据源采集成功率统计显示，{worst['label']} 的成功率为 {worst['success_rate']}%。"
        return cls._base(
            "failure_analysis", "采集失败率分析", narrative,
            [{"type": "table", "title": "来源采集成功率排序",
              "columns": ["source", "success", "total", "rate"],
              "labels": ["数据源", "成功", "总数", "成功率"],
              "data": table}]
        )

    @classmethod
    def _risk_analysis(cls) -> dict:
        """回答：最近有哪些高风险内容？"""
        risk_dist = AnalyticsRepository.risk_level_distribution()
        high_risk = AnalyticsRepository.high_risk_items(15)

        high_count = sum(item["value"] for item in risk_dist if item["label"] in ("high", "critical"))
        narrative = f"检测到 {high_count} 条高风险内容需要关注。"

        table = [
            {
                "title": item["title"][:40],
                "level": item["risk_level"],
                "source": item["source"]
            }
            for item in high_risk
        ]

        return cls._base(
            "risk_analysis", "高风险内容提示", narrative,
            [
                {"type": "bar", "title": "风险等级分布", "data": risk_dist},
                {"type": "table", "title": "高风险项目",
                 "columns": ["title", "level", "source"],
                 "labels": ["标题", "风险等级", "来源"],
                 "data": table}
            ]
        )

    @classmethod
    def _keyword_analysis(cls) -> dict:
        """回答：哪个关键词出现频率最高？"""
        keywords = AnalyticsRepository.keyword_frequency(12)
        if not keywords:
            narrative = "暂无关键词数据。"
            return cls._base(
                "keyword_analysis", "关键词频率分析", narrative,
                [{"type": "kpi", "title": "统计", "data": [{"label": "关键词总数", "value": 0}]}]
            )

        top_keyword = keywords[0]["label"]
        top_count = keywords[0]["value"]
        narrative = f"关键词频率分析显示，'{top_keyword}' 出现 {top_count} 次，是最常见的关键词。"
        return cls._base(
            "keyword_analysis", "关键词频率分析", narrative,
            [{"type": "bar", "title": "关键词出现频率", "data": keywords}]
        )

    @classmethod
    def _performance_analysis(cls) -> dict:
        """回答：各来源平均采集耗时是多少？"""
        performance = AnalyticsRepository.source_performance()
        if not performance:
            narrative = "暂无性能数据。"
            return cls._base(
                "performance_analysis", "采集性能分析", narrative,
                [{"type": "kpi", "title": "性能", "data": [{"label": "平均耗时", "value": 0}]}]
            )

        avg_time = round(sum(item["avg_time"] for item in performance) / len(performance), 2) if performance else 0
        table = [
            {
                "source": item["label"],
                "avg_time": f"{item['avg_time']}s",
                "count": item["total_count"]
            }
            for item in sorted(performance, key=lambda x: x.get("avg_time", 0), reverse=True)[:8]
        ]

        narrative = f"数据源采集性能分析显示，平均耗时为 {avg_time} 秒。"
        return cls._base(
            "performance_analysis", "采集性能分析", narrative,
            [{"type": "table", "title": "来源采集耗时排序",
              "columns": ["source", "avg_time", "count"],
              "labels": ["数据源", "平均耗时", "采集次数"],
              "data": table}]
        )
