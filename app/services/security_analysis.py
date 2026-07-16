"""舆情安全分析模块 - 内容风险评估和敏感词检测。"""

from __future__ import annotations

import json
import logging
from typing import Optional

LOGGER = logging.getLogger("security_analysis")

# 敏感词库（示例）
SENSITIVE_KEYWORDS = {
    "critical": [
        "恐怖", "极端", "暴力", "违法", "犯罪", "诈骗",
        "贩毒", "贩运", "走私", "洗钱", "恐怖融资",
    ],
    "high": [
        "政治", "敏感", "抗争", "游行", "示威", "罢工",
        "泄露", "机密", "谍报", "黑客", "入侵",
    ],
    "medium": [
        "投资风险", "市场波动", "经济衰退", "失业", "债务危机",
        "环境污染", "食品安全", "医疗事故",
    ],
}

# 积极词库（降低风险等级）
POSITIVE_KEYWORDS = {
    "发展", "进步", "改善", "增长", "恢复", "成就",
    "创新", "技术突破", "合作", "和平", "稳定",
}


class SecurityAnalyzer:
    """安全内容分析器。"""

    @staticmethod
    def analyze(title: str, summary: str, content: str = "") -> dict:
        """分析内容的风险等级。

        Args:
            title: 标题
            summary: 摘要
            content: 正文内容

        Returns:
            分析结果字典，包含风险等级、匹配词汇、分析说明等
        """
        text = f"{title} {summary} {content}".lower()

        result = {
            "risk_level": "normal",
            "risk_score": 0.0,
            "matched_words": [],
            "analysis": "",
            "suggestions": [],
        }

        # 检测关键词
        critical_matches = []
        high_matches = []
        medium_matches = []
        positive_matches = []

        for keyword in SENSITIVE_KEYWORDS.get("critical", []):
            if keyword.lower() in text:
                critical_matches.append(keyword)

        for keyword in SENSITIVE_KEYWORDS.get("high", []):
            if keyword.lower() in text:
                high_matches.append(keyword)

        for keyword in SENSITIVE_KEYWORDS.get("medium", []):
            if keyword.lower() in text:
                medium_matches.append(keyword)

        for keyword in POSITIVE_KEYWORDS:
            if keyword.lower() in text:
                positive_matches.append(keyword)

        # 计算风险得分
        risk_score = 0.0
        if critical_matches:
            risk_score += len(critical_matches) * 3.0
            result["risk_level"] = "critical"
        if high_matches:
            risk_score += len(high_matches) * 2.0
            if result["risk_level"] == "normal":
                result["risk_level"] = "high"
        if medium_matches:
            risk_score += len(medium_matches) * 1.0
            if result["risk_level"] in ("normal",):
                result["risk_level"] = "high"

        # 正面词汇降低风险
        if positive_matches:
            risk_score = max(0.0, risk_score - len(positive_matches) * 0.5)

        # 标准化风险得分到 0-10
        result["risk_score"] = min(10.0, max(0.0, risk_score / 2.0))

        # 如果没有匹配任何关键词，设为正常
        if not (critical_matches or high_matches or medium_matches):
            result["risk_level"] = "normal"
            result["risk_score"] = 0.5  # 基础得分
            result["analysis"] = "内容未检测到敏感信息。"
        else:
            all_matches = critical_matches + high_matches + medium_matches
            result["matched_words"] = all_matches
            result["analysis"] = (
                f"检测到 {len(all_matches)} 个敏感词汇。"
                f"其中关键词 {critical_matches or high_matches or []} 风险等级较高，"
                f"建议重点关注。"
            )

        # 生成建议
        if result["risk_level"] == "critical":
            result["suggestions"].append("需要立即审查和处理")
            result["suggestions"].append("建议上报相关部门")
        elif result["risk_level"] == "high":
            result["suggestions"].append("建议人工审查")
            result["suggestions"].append("考虑标记为高优先级")
        elif result["risk_level"] == "normal":
            result["suggestions"].append("定期监测")

        return result

    @staticmethod
    def batch_analyze(items: list[dict]) -> list[dict]:
        """批量分析多个项目。

        Args:
            items: 包含 title, summary, content 字段的字典列表

        Returns:
            分析结果列表
        """
        results = []
        for item in items:
            analysis = SecurityAnalyzer.analyze(
                title=item.get("title", ""),
                summary=item.get("summary", ""),
                content=item.get("content", ""),
            )
            results.append({**item, "security_analysis": analysis})
        return results

    @staticmethod
    def get_risk_level_from_score(score: float) -> str:
        """从分数获取风险等级。

        Args:
            score: 风险分数 (0-10)

        Returns:
            风险等级字符串
        """
        if score >= 8.0:
            return "critical"
        elif score >= 6.0:
            return "high"
        elif score >= 3.0:
            return "normal"
        else:
            return "low"


def analyze_content_security(
    title: str, summary: str, content: str = ""
) -> tuple[str, dict]:
    """便利函数：分析内容安全性。

    Args:
        title: 标题
        summary: 摘要
        content: 内容

    Returns:
        (风险等级, 分析结果字典)元组
    """
    result = SecurityAnalyzer.analyze(title=title, summary=summary, content=content)
    return result["risk_level"], result
