"""舆情安全分析模块 - 内容风险评估和敏感词检测。"""

from __future__ import annotations

import logging

LOGGER = logging.getLogger("security_analysis")

# 敏感词库：使用具体短语而非「政治」「暴力」等泛词，以降低误报。
SENSITIVE_KEYWORDS = {
    # 政治安全 / 暴恐：真实高风险，需立即处置
    "critical": [
        "颠覆国家政权", "颠覆政府", "分裂国家", "煽动分裂",
        "民族分裂", "危害国家安全", "境外渗透", "武装叛乱",
        "恐怖袭击", "恐怖主义", "暴力恐怖", "制造爆炸", "邪教组织",
    ],
    # 社会稳定 / 失泄密 / 敌对舆论 / 廉政：重点关注
    "high": [
        "群体性事件", "非法集会", "非法游行", "聚众闹事", "聚众滋事",
        "打砸抢烧", "煽动闹事", "造谣传谣", "网络谣言",
        "境外势力", "敌对势力", "反华势力",
        "泄露国家机密", "泄露机密", "军事机密", "数据泄露",
        "网络攻击", "黑客入侵", "官商勾结", "权钱交易", "严重腐败",
    ],
    # 公共安全 / 经济金融 / 民生：常规监测
    "medium": [
        "重大安全事故", "食品安全事故", "环境污染事件", "医疗事故", "疫情扩散",
        "非法集资", "集资诈骗", "债务违约", "楼盘烂尾", "大规模裁员",
        "强制拆迁", "拖欠工资", "暴力执法", "群体投诉",
    ],
}

# 执法 / 处置类语境，通常为正面报道，用于抑制非关键级误报。
ENFORCEMENT_CONTEXT = (
    "打击", "严打", "破获", "侦破", "查处", "取缔", "整治",
    "严禁", "抓获", "逮捕", "判处", "依法惩处", "专项行动", "防范化解",
)

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

        # 计算风险得分（同一等级内取最高级，避免单个中危词误升为高危）
        risk_score = 0.0
        if critical_matches:
            risk_score += len(critical_matches) * 3.0
            result["risk_level"] = "critical"
        elif high_matches:
            risk_score += len(high_matches) * 2.0
            result["risk_level"] = "high"
        elif medium_matches:
            risk_score += len(medium_matches) * 1.0
            result["risk_level"] = "normal"

        # 正面词汇降低风险
        if positive_matches:
            risk_score = max(0.0, risk_score - len(positive_matches) * 0.5)

        # 执法/处置语境抑制误报：非关键级内容若明显为正面执法报道，则下调等级
        enforcement_matches = [word for word in ENFORCEMENT_CONTEXT if word in text]
        if enforcement_matches and not critical_matches:
            risk_score = max(0.0, risk_score - len(enforcement_matches) * 1.0)
            if result["risk_level"] == "high" and len(high_matches) <= 1:
                result["risk_level"] = "normal"

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
