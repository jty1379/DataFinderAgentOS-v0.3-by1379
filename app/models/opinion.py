"""舆情安全后端 Repository。"""

from __future__ import annotations

import json
import math
import re

from app.models.db import connection_scope

# 早期课堂占位词，仅用于清理，避免污染真实预警统计。
LEGACY_PLACEHOLDER_WORDS = ("敏感词示例1", "敏感词示例2", "测试敏感词")

# 舆情风险关键词基线库。
# level 语义：4=立即处置 3=重点关注 2=常规监测 1=提示关注。
# 词条尽量使用具体短语（而非「政治」「暴力」等泛词），以减少误报并覆盖真实风险。
DEFAULT_SENSITIVE_WORDS = [
    # —— 政治安全（立即处置）——
    ("颠覆国家政权", "政治安全", 4, "危害国家政权安全"),
    ("颠覆政府", "政治安全", 4, "危害国家政权安全"),
    ("分裂国家", "政治安全", 4, "破坏国家统一"),
    ("煽动分裂", "政治安全", 4, "煽动民族/国家分裂"),
    ("民族分裂", "政治安全", 4, "破坏民族团结"),
    ("危害国家安全", "政治安全", 4, "危害国家安全"),
    ("境外渗透", "政治安全", 4, "境外势力渗透"),
    ("武装叛乱", "政治安全", 4, "武装暴动"),
    # —— 暴恐（立即处置）——
    ("恐怖袭击", "暴恐", 4, "暴力恐怖袭击"),
    ("恐怖主义", "暴恐", 4, "恐怖主义活动"),
    ("暴力恐怖", "暴恐", 4, "暴力恐怖活动"),
    ("制造爆炸", "暴恐", 4, "制造爆炸装置/袭击"),
    ("邪教组织", "暴恐", 4, "邪教及非法宗教组织"),
    # —— 社会稳定（重点关注）——
    ("群体性事件", "社会稳定", 3, "规模性聚集事件"),
    ("非法集会", "社会稳定", 3, "未经许可的集会"),
    ("非法游行", "社会稳定", 3, "未经许可的游行"),
    ("聚众闹事", "社会稳定", 3, "聚众扰乱秩序"),
    ("聚众滋事", "社会稳定", 3, "聚众扰乱秩序"),
    ("打砸抢烧", "社会稳定", 3, "暴力打砸"),
    ("煽动闹事", "社会稳定", 3, "煽动聚集闹事"),
    # —— 失泄密 / 网络安全（重点关注）——
    ("泄露国家机密", "失泄密", 3, "泄露国家秘密"),
    ("泄露机密", "失泄密", 3, "泄露涉密信息"),
    ("军事机密", "失泄密", 3, "涉军涉密信息"),
    ("数据泄露", "网络安全", 3, "重要数据泄露"),
    ("网络攻击", "网络安全", 3, "网络攻击/入侵"),
    ("黑客入侵", "网络安全", 3, "黑客入侵"),
    # —— 敌对舆论（重点关注）——
    ("造谣传谣", "敌对舆论", 3, "编造传播谣言"),
    ("网络谣言", "敌对舆论", 3, "网络不实信息"),
    ("境外势力", "敌对舆论", 3, "境外势力介入"),
    ("敌对势力", "敌对舆论", 3, "敌对势力活动"),
    ("反华势力", "敌对舆论", 3, "反华言论/势力"),
    # —— 廉政（重点关注）——
    ("官商勾结", "廉政", 3, "官商勾结"),
    ("权钱交易", "廉政", 3, "权钱交易"),
    ("严重腐败", "廉政", 3, "重大腐败问题"),
    # —— 公共安全（常规监测）——
    ("重大安全事故", "公共安全", 2, "重大生产安全事故"),
    ("食品安全事故", "公共安全", 2, "食品安全问题"),
    ("环境污染事件", "公共安全", 2, "环境污染"),
    ("医疗事故", "公共安全", 2, "医疗事故"),
    ("疫情扩散", "公共安全", 2, "疫情蔓延"),
    # —— 经济金融（常规监测）——
    ("非法集资", "经济金融", 2, "非法集资"),
    ("集资诈骗", "经济金融", 2, "集资诈骗"),
    ("债务违约", "经济金融", 2, "重大债务违约"),
    ("楼盘烂尾", "经济金融", 2, "项目烂尾"),
    ("大规模裁员", "经济金融", 2, "规模性裁员"),
    # —— 民生（常规监测）——
    ("强制拆迁", "民生", 2, "强制/暴力拆迁"),
    ("拖欠工资", "民生", 2, "欠薪问题"),
    ("暴力执法", "民生", 2, "执法不当"),
    ("群体投诉", "民生", 2, "规模性投诉"),
    # —— 信访维权（提示关注）——
    ("集体上访", "信访维权", 1, "集体上访"),
    ("越级上访", "信访维权", 1, "越级上访"),
    ("静坐抗议", "信访维权", 1, "静坐/拉横幅抗议"),
]


class SensitiveWordRepository:
    @staticmethod
    def list_words(keyword: str = "", category: str = "", page: int = 1, page_size: int = 20):
        pattern = f"%{keyword}%"
        # sensitive_words 无 source_type 列，此处仅按可选的关键词/分类过滤。
        clauses = []
        params = []
        if keyword:
            clauses.append("word LIKE ?")
            params.append(pattern)
        if category:
            clauses.append("category = ?")
            params.append(category)
        
        where_sql = " AND ".join(clauses) if clauses else "1=1"
        
        with connection_scope() as connection:
            total_row = connection.execute(
                f"SELECT COUNT(*) AS total FROM sensitive_words WHERE {where_sql}", params
            ).fetchone()
            total = int(total_row["total"])
            offset = (page - 1) * page_size
            rows = connection.execute(
                f"SELECT * FROM sensitive_words WHERE {where_sql} ORDER BY level DESC, word LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            ).fetchall()
        
        total_pages = max(1, math.ceil(total / page_size))
        return [dict(row) for row in rows], {
            "page": page, "page_size": page_size, "total": total, "total_pages": total_pages
        }

    @staticmethod
    def get(word_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT * FROM sensitive_words WHERE id = ?", (word_id,)
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def create(word: str, category: str = "default", level: int = 1, description: str = "", user_id: int = None):
        try:
            with connection_scope() as connection:
                connection.execute(
                    """
                    INSERT INTO sensitive_words (word, category, level, description, created_by)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (word, category, level, description, user_id),
                )
                connection.commit()
            return True
        except Exception:
            return False

    @staticmethod
    def update(word_id: int, word: str, category: str, level: int, description: str, enabled: bool):
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    UPDATE sensitive_words SET word = ?, category = ?, level = ?, description = ?,
                                               enabled = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (word, category, level, description, int(enabled), word_id),
                )
                connection.commit()
            return cursor.rowcount == 1
        except Exception:
            return False

    @staticmethod
    def delete(word_id: int):
        with connection_scope() as connection:
            cursor = connection.execute(
                "DELETE FROM sensitive_words WHERE id = ?", (word_id,)
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def search(content: str) -> list[dict]:
        with connection_scope() as connection:
            rows = connection.execute(
                "SELECT id, word, category, level FROM sensitive_words WHERE enabled = 1"
            ).fetchall()
        
        results = []
        for row in rows:
            word = row["word"]
            if re.search(re.escape(word), content, re.IGNORECASE):
                results.append(dict(row))
        return results

    @staticmethod
    def seed_defaults(connection) -> None:
        # 先清理早期课堂占位词，避免其继续产生无意义预警。
        connection.execute(
            "DELETE FROM sensitive_words WHERE word IN (%s)"
            % ",".join("?" * len(LEGACY_PLACEHOLDER_WORDS)),
            LEGACY_PLACEHOLDER_WORDS,
        )
        for word, category, level, description in DEFAULT_SENSITIVE_WORDS:
            connection.execute(
                """
                INSERT OR IGNORE INTO sensitive_words (word, category, level, description)
                VALUES (?, ?, ?, ?)
                """,
                (word, category, level, description),
            )


class OpinionAlertRepository:
    @staticmethod
    def list_alerts(
        status: str = "",
        risk_level: str = "",
        user_id: int = None,
        page: int = 1,
        page_size: int = 20,
    ):
        clauses = ["a.source_type = ?"]
        params = ["chat"]
        if status:
            clauses.append("a.status = ?")
            params.append(status)
        if risk_level:
            clauses.append("a.risk_level = ?")
            params.append(risk_level)
        if user_id:
            clauses.append("a.user_id = ?")
            params.append(user_id)
        
        where_sql = " AND ".join(clauses) if clauses else "1=1"
        
        with connection_scope() as connection:
            total_row = connection.execute(
                f"SELECT COUNT(*) AS total FROM opinion_alerts a WHERE {where_sql}", params
            ).fetchone()
            total = int(total_row["total"])
            offset = (page - 1) * page_size
            rows = connection.execute(
                f"""
                SELECT a.*, u.username AS user_name, h.username AS handler_name
                FROM opinion_alerts a
                LEFT JOIN users u ON u.id = a.user_id
                LEFT JOIN users h ON h.id = a.handled_by
                WHERE {where_sql}
                ORDER BY a.created_at DESC LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()
        
        total_pages = max(1, math.ceil(total / page_size))
        return [dict(row) for row in rows], {
            "page": page, "page_size": page_size, "total": total, "total_pages": total_pages
        }

    @staticmethod
    def get(alert_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT a.*, u.username AS user_name,
                       handler.username AS handled_by_name
                FROM opinion_alerts a
                LEFT JOIN users u ON u.id = a.user_id
                LEFT JOIN users handler ON handler.id = a.handled_by
                WHERE a.id = ? AND a.source_type='chat'
                """,
                (alert_id,),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def create(
        source_type: str,
        source_id: int,
        user_id: int,
        content: str,
        matched_words: list[dict],
        risk_level: str = "low",
        ai_analysis: str = "",
        content_hash: str = "",
        metadata: dict | None = None,
    ):
        try:
            with connection_scope() as connection:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO opinion_alerts
                    (source_type, source_id, user_id, title, content, excerpt,
                     matched_words, risk_level, ai_analysis, content_hash, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_type,
                        source_id,
                        user_id,
                        content[:80],
                        content,
                        content[:500],
                        json.dumps(matched_words, ensure_ascii=False),
                        risk_level,
                        ai_analysis,
                        content_hash,
                        json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                connection.commit()
                if cursor.rowcount:
                    return int(cursor.lastrowid)
                row = connection.execute(
                    """SELECT id FROM opinion_alerts
                       WHERE source_type=? AND source_id=? AND content_hash=?""",
                    (source_type, source_id, content_hash),
                ).fetchone()
            return int(row["id"]) if row else 0
        except Exception:
            return 0

    @staticmethod
    def update_status(alert_id: int, status: str, handled_by: int, handle_note: str = ""):
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                UPDATE opinion_alerts
                SET status = ?, handled_by = ?, handle_note = ?, handled_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, handled_by, handle_note, alert_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def delete(alert_id: int):
        with connection_scope() as connection:
            cursor = connection.execute(
                "DELETE FROM opinion_alerts WHERE id = ?", (alert_id,)
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def count_by_status():
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM opinion_alerts
                WHERE source_type='chat'
                GROUP BY status
                """
            ).fetchall()
        return {row["status"]: row["count"] for row in rows}

    @staticmethod
    def count_by_risk():
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT risk_level, COUNT(*) AS count
                FROM opinion_alerts
                WHERE source_type='chat'
                GROUP BY risk_level
                """
            ).fetchall()
        return {row["risk_level"]: row["count"] for row in rows}


class AuditLogRepository:
    @staticmethod
    def create(
        action_type: str,
        resource_type: str,
        resource_id: int = None,
        user_id: int = None,
        user_name: str = "",
        ip_address: str = "",
        action_before: dict = None,
        action_after: dict = None,
        detail: str = "",
        success: bool = True,
        error_message: str = "",
    ):
        try:
            with connection_scope() as connection:
                connection.execute(
                    """
                    INSERT INTO audit_logs
                    (action_type, resource_type, resource_id, user_id, user_name, ip_address,
                     action_before, action_after, detail, success, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        action_type,
                        resource_type,
                        resource_id,
                        user_id,
                        user_name,
                        ip_address,
                        json.dumps(action_before or {}, ensure_ascii=False),
                        json.dumps(action_after or {}, ensure_ascii=False),
                        detail,
                        int(success),
                        error_message,
                    ),
                )
                connection.commit()
            return True
        except Exception:
            return False

    @staticmethod
    def list_logs(
        action_type: str = "",
        user_id: int = None,
        resource_type: str = "",
        resource_id: int | None = None,
        start_date: str = "",
        end_date: str = "",
        page: int = 1,
        page_size: int = 20,
    ):
        clauses = []
        params = []
        if action_type:
            clauses.append("action_type = ?")
            params.append(action_type)
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if resource_type:
            clauses.append("resource_type = ?")
            params.append(resource_type)
        if resource_id:
            clauses.append("resource_id = ?")
            params.append(resource_id)
        if start_date:
            clauses.append("date(created_at) >= date(?)")
            params.append(start_date)
        if end_date:
            clauses.append("date(created_at) <= date(?)")
            params.append(end_date)
        
        where_sql = " AND ".join(clauses) if clauses else "1=1"
        
        with connection_scope() as connection:
            total_row = connection.execute(
                f"SELECT COUNT(*) AS total FROM audit_logs WHERE {where_sql}", params
            ).fetchone()
            total = int(total_row["total"])
            offset = (page - 1) * page_size
            rows = connection.execute(
                f"""
                SELECT * FROM audit_logs
                WHERE {where_sql}
                ORDER BY created_at DESC LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()
        
        total_pages = max(1, math.ceil(total / page_size))
        return [dict(row) for row in rows], {
            "page": page, "page_size": page_size, "total": total, "total_pages": total_pages
        }
