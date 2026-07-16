"""舆情安全服务。"""

from __future__ import annotations

import hashlib
import logging

from app.models.opinion import OpinionAlertRepository, SensitiveWordRepository
from app.services.system_settings import SystemSettingsService

LOGGER = logging.getLogger("app")


RISK_LEVELS = ["low", "medium", "high", "critical"]


class OpinionSecurityService:
    @staticmethod
    def analyze_and_record(
        source_type: str,
        source_id: int,
        content: str,
        user_id: int | None = None,
        metadata: dict | None = None,
    ) -> dict:
        source_type = source_type if source_type in {"chat", "collection", "employee", "news"} else "collection"
        content = str(content or "")[:12000]
        analysis = OpinionSecurityService.analyze_content_security(
            content, source_type, int(source_id), int(user_id or 0),
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            metadata=metadata,
        )
        return {
            "source_type": source_type,
            "source_id": int(source_id),
            **analysis,
        }

    @staticmethod
    def analyze_content_security(
        content: str,
        source_type: str = "chat",
        source_id: int = 0,
        user_id: int = 0,
        *,
        content_hash: str = "",
        metadata: dict | None = None,
    ) -> dict:
        matched_words = SensitiveWordRepository.search(content)
        
        risk_level = "low"
        if matched_words:
            max_level = max(word["level"] for word in matched_words)
            if max_level == 4:
                risk_level = "critical"
            elif max_level == 3:
                risk_level = "high"
            elif max_level == 2:
                risk_level = "medium"
        
        ai_analysis = ""
        if risk_level != "low":
            ai_analysis = f"检测到 {len(matched_words)} 个敏感词，风险等级为 {risk_level}"
        
        alert_id = 0
        if matched_words:
            threshold = SystemSettingsService.get_integer("sensitive_word_threshold", 1)
            if len(matched_words) >= threshold:
                alert_id = OpinionAlertRepository.create(
                    source_type=source_type,
                    source_id=source_id,
                    user_id=user_id,
                    content=content[:500],
                    matched_words=matched_words,
                    risk_level=risk_level,
                    ai_analysis=ai_analysis,
                    content_hash=content_hash,
                    metadata=metadata,
                )
        
        return {
            "risk_level": risk_level,
            "matched_words": matched_words,
            "ai_analysis": ai_analysis,
            "alert_id": alert_id,
        }

    @staticmethod
    def get_alerts(status: str = "", risk_level: str = "", user_id: int = None, page: int = 1, page_size: int = 20):
        return OpinionAlertRepository.list_alerts(status, risk_level, user_id, page, page_size)

    @staticmethod
    def get_alert(alert_id: int):
        return OpinionAlertRepository.get(alert_id)

    @staticmethod
    def handle_alert(alert_id: int, status: str, handled_by: int, handle_note: str = ""):
        return OpinionAlertRepository.update_status(alert_id, status, handled_by, handle_note)

    @staticmethod
    def get_alert_stats():
        return {
            "by_status": OpinionAlertRepository.count_by_status(),
            "by_risk": OpinionAlertRepository.count_by_risk(),
        }

    @staticmethod
    def _delete_alert(alert_id: int):
        return OpinionAlertRepository.delete(alert_id)

    @staticmethod
    def add_sensitive_word(word: str, category: str = "default", level: int = 1, description: str = "", user_id: int = None):
        return SensitiveWordRepository.create(word, category, level, description, user_id)

    @staticmethod
    def update_sensitive_word(word_id: int, word: str, category: str, level: int, description: str, enabled: bool):
        return SensitiveWordRepository.update(word_id, word, category, level, description, enabled)

    @staticmethod
    def delete_sensitive_word(word_id: int):
        return SensitiveWordRepository.delete(word_id)

    @staticmethod
    def get_sensitive_words(keyword: str = "", category: str = "", page: int = 1, page_size: int = 20):
        return SensitiveWordRepository.list_words(keyword, category, page, page_size)
