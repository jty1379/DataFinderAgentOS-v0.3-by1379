"""管理控制台、数智大屏与舆情大屏的只读统计 Repository。"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime

from app.models.db import connection_scope

RISK_WORDS = {
    "critical": ("爆炸", "死亡", "数据泄露", "重大事故"),
    "high": ("火灾", "诈骗", "污染", "事故", "泄露"),
    "medium": ("投诉", "故障", "风险", "预警", "异常"),
    "low": ("关注", "延迟", "波动"),
}
DOMAIN_WORDS = (
    "政务",
    "数据",
    "采集",
    "模型",
    "风险",
    "新闻",
    "天气",
    "用户",
    "分析",
    "预警",
    "舆情",
    "报告",
)
CITY_COORDINATES = {
    "北京": (116.40, 39.90),
    "上海": (121.47, 31.23),
    "成都": (104.07, 30.67),
    "广州": (113.26, 23.13),
    "深圳": (114.06, 22.55),
    "武汉": (114.30, 30.59),
    "西安": (108.94, 34.34),
    "杭州": (120.15, 30.28),
    "重庆": (106.55, 29.56),
    "南京": (118.80, 32.06),
}


def _count(connection, sql: str, params: tuple = ()) -> int:
    return int(connection.execute(sql, params).fetchone()[0] or 0)


def _daily(connection, table: str, date_column: str, days: int = 7) -> list[dict]:
    allowed = {
        ("collection_results", "created_at"),
        ("model_usage", "created_at"),
        ("user_messages", "created_at"),
        ("user_conversations", "created_at"),
        ("opinion_alerts", "created_at"),
    }
    if (table, date_column) not in allowed:
        raise ValueError("统计数据表不在白名单")
    rows = connection.execute(
        f"""
        WITH RECURSIVE dates(day, remaining) AS (
            SELECT date('now', ?), ?
            UNION ALL SELECT date(day, '+1 day'), remaining - 1 FROM dates WHERE remaining > 1
        )
        SELECT dates.day AS label, COUNT(t.rowid) AS value
        FROM dates LEFT JOIN {table} t ON substr(t.{date_column}, 1, 10)=dates.day
        GROUP BY dates.day ORDER BY dates.day
        """,
        (f"-{days - 1} day", days),
    ).fetchall()
    return [{"label": row["label"], "value": int(row["value"])} for row in rows]


def _risk(text: str) -> tuple[str, list[str]] | None:
    found: list[str] = []
    selected = "low"
    for level in ("critical", "high", "medium", "low"):
        hits = [word for word in RISK_WORDS[level] if word in text]
        if hits:
            found.extend(hits)
            if selected == "low":
                selected = level
    if not found:
        return None
    rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    selected = max(
        (level for level, words in RISK_WORDS.items() if any(word in text for word in words)),
        key=lambda item: rank[item],
    )
    return selected, sorted(set(found))


class DashboardRepository:
    @staticmethod
    def sync_opinion_alerts(limit: int = 100) -> int:
        """从真实用户消息和入仓内容生成可追溯预警，不写入演示假数据。"""
        inserted = 0
        with connection_scope() as connection:
            candidates = connection.execute(
                """
                SELECT * FROM (
                    SELECT 'chat' AS source_type, m.id AS source_id,
                           c.title AS title, m.content AS body, m.created_at AS created_at
                    FROM user_messages m
                    JOIN user_conversations c ON c.id=m.conversation_id
                    LEFT JOIN opinion_alerts a ON a.source_type='chat' AND a.source_id=m.id
                    WHERE a.id IS NULL
                    UNION ALL
                    SELECT 'collection' AS source_type, w.id AS source_id, w.title AS title,
                           COALESCE(NULLIF(w.content,''), NULLIF(w.summary,''), w.title) AS body,
                           w.created_at AS created_at
                    FROM warehouse_items w
                    LEFT JOIN opinion_alerts a ON a.source_type='collection' AND a.source_id=w.id
                    WHERE a.id IS NULL
                ) candidates ORDER BY created_at DESC LIMIT ?
                """,
                (max(1, min(500, int(limit))),),
            ).fetchall()
            for row in candidates:
                body = str(row["body"] or "")[:12000]
                analysis = _risk(f"{row['title']} {body}")
                if not analysis:
                    continue
                level, words = analysis
                label = {"low": "低", "medium": "中", "high": "高", "critical": "重大"}[level]
                connection.execute(
                    """
                    INSERT OR IGNORE INTO opinion_alerts
                    (source_type, source_id, title, content, excerpt, risk_level, matched_words,
                     ai_analysis, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        row["source_type"],
                        row["source_id"],
                        str(row["title"] or "未命名内容")[:300],
                        body,
                        body[:500],
                        level,
                        json.dumps(words, ensure_ascii=False),
                        f"智能规则识别到{label}风险，命中关键词：{'、'.join(words)}。建议结合原始内容人工复核。",
                        row["created_at"],
                        row["created_at"],
                    ),
                )
                inserted += int(connection.execute("SELECT changes()").fetchone()[0] or 0)
            connection.commit()
        return inserted

    @staticmethod
    def overview() -> dict:
        DashboardRepository.sync_opinion_alerts()
        with connection_scope() as connection:
            total_runs = _count(connection, "SELECT COUNT(*) FROM collection_runs WHERE date(created_at)=date('now')")
            successful_runs = _count(connection, "SELECT COUNT(*) FROM collection_runs WHERE date(created_at)=date('now') AND status='success'")
            metrics = {
                "user_count": _count(connection, "SELECT COUNT(*) FROM users WHERE status='enabled'"),
                "today_conversations": _count(connection, "SELECT COUNT(*) FROM user_conversations WHERE date(created_at)=date('now')"),
                "model_calls": _count(connection, "SELECT COUNT(*) FROM model_usage WHERE date(created_at)=date('now')"),
                "today_collection": _count(connection, "SELECT COUNT(*) FROM collection_results WHERE date(created_at)=date('now')"),
                "collection_success_rate": round(successful_runs * 100 / total_runs) if total_runs else 0,
                "high_risk_alerts": _count(connection, "SELECT COUNT(*) FROM opinion_alerts WHERE risk_level IN ('high','critical') AND status IN ('pending','processing')"),
                "employee_count": _count(connection, "SELECT COUNT(*) FROM digital_employees WHERE enabled=1"),
                "source_count": _count(connection, "SELECT COUNT(*) FROM lookout_sources WHERE enabled=1"),
            }
            recent_tasks = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT '采集' AS task_type, 'COL-' || id AS task_no,
                           keyword AS title, status, result_count AS amount, created_at
                    FROM collection_runs
                    UNION ALL
                    SELECT '深采', 'DEEP-' || t.id, w.title, t.status,
                           t.progress, t.created_at
                    FROM deep_collection_tasks t JOIN warehouse_items w ON w.id=t.warehouse_item_id
                    ORDER BY created_at DESC LIMIT 8
                    """
                ).fetchall()
            ]
            model_errors = [
                dict(row)
                for row in connection.execute(
                    """SELECT m.name AS model_name, u.error_message, u.created_at
                       FROM model_usage u JOIN model_configs m ON m.id=u.model_id
                       WHERE u.success=0 ORDER BY u.id DESC LIMIT 5"""
                ).fetchall()
            ]
            service_status = {
                "database": "normal",
                "collection": "normal" if not total_runs or successful_runs else "warning",
                "model": "warning" if model_errors else "normal",
            }
            query_trend = _daily(connection, "user_conversations", "created_at", 7)
            collection_trend = _daily(connection, "collection_results", "created_at", 7)
            metrics["week_conversations"] = sum(item["value"] for item in query_trend)
        return {
            "metrics": metrics,
            "recent_tasks": recent_tasks,
            "model_errors": model_errors,
            "service_status": service_status,
            "query_trend": query_trend,
            "collection_trend": collection_trend,
            "refreshed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    @staticmethod
    def intelligence() -> dict:
        overview = DashboardRepository.overview()
        with connection_scope() as connection:
            source_distribution = [
                {"label": row["label"], "value": int(row["value"])}
                for row in connection.execute(
                    """SELECT COALESCE(NULLIF(source_name,''),'未标注来源') AS label, COUNT(*) AS value
                       FROM warehouse_items GROUP BY label ORDER BY value DESC LIMIT 8"""
                ).fetchall()
            ]
            text_rows = connection.execute(
                "SELECT title || ' ' || summary AS body FROM warehouse_items ORDER BY id DESC LIMIT 300"
            ).fetchall()
            corpus = " ".join(str(row["body"] or "") for row in text_rows)
            word_cloud = [{"name": word, "value": corpus.count(word)} for word in DOMAIN_WORDS if corpus.count(word)]
            word_cloud.sort(key=lambda item: item["value"], reverse=True)
            hotspots = [
                dict(row)
                for row in connection.execute(
                    """SELECT id, title, COALESCE(NULLIF(source_name,''),'未标注来源') AS source,
                              created_at FROM warehouse_items ORDER BY id DESC LIMIT 10"""
                ).fetchall()
            ]
            risk_distribution = [
                {"label": row["risk_level"], "value": int(row["value"])}
                for row in connection.execute(
                    "SELECT risk_level, COUNT(*) AS value FROM opinion_alerts GROUP BY risk_level"
                ).fetchall()
            ]
            geo_points = [
                {"name": city, "value": [longitude, latitude, corpus.count(city)]}
                for city, (longitude, latitude) in CITY_COORDINATES.items()
                if corpus.count(city)
            ]
        return {
            **overview,
            "source_distribution": source_distribution,
            "collection_trend": DashboardRepository._trend("collection_results"),
            "model_trend": DashboardRepository._trend("model_usage"),
            "user_activity": DashboardRepository._trend("user_messages"),
            "word_cloud": word_cloud[:20],
            "hotspots": hotspots,
            "risk_distribution": risk_distribution,
            "geo_points": geo_points,
            "refreshed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    @staticmethod
    def _trend(table: str) -> list[dict]:
        with connection_scope() as connection:
            return _daily(connection, table, "created_at", 7)

    @staticmethod
    def opinion() -> dict:
        DashboardRepository.sync_opinion_alerts()
        with connection_scope() as connection:
            summary = {
                "total": _count(connection, "SELECT COUNT(*) FROM opinion_alerts"),
                "today": _count(connection, "SELECT COUNT(*) FROM opinion_alerts WHERE date(created_at)=date('now')"),
                "open": _count(connection, "SELECT COUNT(*) FROM opinion_alerts WHERE status IN ('pending','processing')"),
                "critical": _count(connection, "SELECT COUNT(*) FROM opinion_alerts WHERE risk_level='critical' AND status IN ('pending','processing')"),
            }
            rows = connection.execute("SELECT * FROM opinion_alerts ORDER BY CASE risk_level WHEN 'critical' THEN 4 WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC, id DESC LIMIT 30").fetchall()
            alerts = []
            words: Counter[str] = Counter()
            for row in rows:
                item = dict(row)
                try:
                    parsed_words = json.loads(item["matched_words"] or "[]")
                    item["sensitive_words"] = [
                        str(entry.get("word") or "") if isinstance(entry, dict) else str(entry)
                        for entry in parsed_words
                        if (entry.get("word") if isinstance(entry, dict) else entry)
                    ]
                except json.JSONDecodeError:
                    item["sensitive_words"] = []
                words.update(item["sensitive_words"])
                alerts.append(item)
            risk_distribution = [{"label": row["risk_level"], "value": int(row["value"])} for row in connection.execute("SELECT risk_level, COUNT(*) AS value FROM opinion_alerts GROUP BY risk_level").fetchall()]
            status_distribution = [{"label": row["status"], "value": int(row["value"])} for row in connection.execute("SELECT status, COUNT(*) AS value FROM opinion_alerts GROUP BY status").fetchall()]
            source_ratio = [{"label": row["source_type"], "value": int(row["value"])} for row in connection.execute("SELECT source_type, COUNT(*) AS value FROM opinion_alerts GROUP BY source_type").fetchall()]
        return {
            "summary": summary,
            "alerts": alerts,
            "risk_distribution": risk_distribution,
            "status_distribution": status_distribution,
            "source_ratio": source_ratio,
            "sensitive_words": [{"name": name, "value": value} for name, value in words.most_common(12)],
            "risk_trend": DashboardRepository._trend("opinion_alerts"),
            "refreshed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    @staticmethod
    def update_alert(alert_id: int, status: str, note: str, user_id: int) -> bool:
        if status not in {"processing", "resolved", "false_positive"}:
            raise ValueError("预警状态不正确")
        note = str(note or "").strip()
        if not note:
            raise ValueError("请填写处理备注")
        with connection_scope() as connection:
            cursor = connection.execute(
                """UPDATE opinion_alerts SET status=?, handle_note=?, handled_by=?,
                   handled_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (status, note[:1000], user_id, int(alert_id)),
            )
            connection.commit()
        return bool(cursor.rowcount)
