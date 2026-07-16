"""Read-only, allowlisted analytics queries for the user question workspace."""

from __future__ import annotations

from app.models.db import connection_scope


class AnalyticsRepository:
    """Expose bounded statistics without accepting SQL fragments from callers."""

    @staticmethod
    def overview() -> dict:
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM warehouse_items) AS warehouse_count,
                    (SELECT COUNT(*) FROM warehouse_items WHERE deep_collected=1) AS deep_count,
                    (SELECT COUNT(*) FROM lookout_sources WHERE enabled=1) AS source_count,
                    (SELECT COUNT(*) FROM collection_results) AS collected_count,
                    (SELECT COUNT(*) FROM collection_runs WHERE status='success') AS successful_runs
                """
            ).fetchone()
        return {key: int(row[key] or 0) for key in row.keys()}

    @staticmethod
    def source_distribution(limit: int = 8) -> list[dict]:
        limit = min(12, max(1, int(limit)))
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT CASE WHEN TRIM(source_name)='' THEN '未标注来源' ELSE source_name END AS label,
                       COUNT(*) AS value
                FROM warehouse_items
                GROUP BY CASE WHEN TRIM(source_name)='' THEN '未标注来源' ELSE source_name END
                ORDER BY value DESC, label ASC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{"label": str(row["label"]), "value": int(row["value"])} for row in rows]

    @staticmethod
    def daily_trend(days: int = 7) -> list[dict]:
        days = min(30, max(4, int(days)))
        with connection_scope() as connection:
            rows = connection.execute(
                """
                WITH RECURSIVE dates(day, remaining) AS (
                    SELECT date('now', ?), ?
                    UNION ALL
                    SELECT date(day, '+1 day'), remaining - 1 FROM dates WHERE remaining > 1
                )
                SELECT dates.day AS label, COUNT(w.id) AS value
                FROM dates LEFT JOIN warehouse_items w
                    ON substr(w.created_at, 1, 10)=dates.day
                GROUP BY dates.day ORDER BY dates.day
                """,
                (f"-{days - 1} day", days),
            ).fetchall()
        return [{"label": str(row["label"]), "value": int(row["value"])} for row in rows]

    @staticmethod
    def deep_status() -> list[dict]:
        overview = AnalyticsRepository.overview()
        deep = overview["deep_count"]
        return [
            {"label": "已深度采集", "value": deep},
            {"label": "待深度采集", "value": max(0, overview["warehouse_count"] - deep)},
        ]

    @staticmethod
    def recent_items(limit: int = 8) -> list[dict]:
        limit = min(20, max(1, int(limit)))
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT id, title, source_name, summary, deep_collected, created_at
                FROM warehouse_items ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "title": str(row["title"]),
                "source": str(row["source_name"] or "未标注来源"),
                "summary": str(row["summary"] or "")[:180],
                "deep_collected": bool(row["deep_collected"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    @staticmethod
    def relationship_graph(limit: int = 12) -> dict:
        items = AnalyticsRepository.recent_items(min(20, max(3, int(limit))))
        sources: dict[str, str] = {}
        nodes: list[dict] = []
        edges: list[dict] = []
        for item in items:
            source = item["source"]
            source_id = sources.setdefault(source, f"source:{len(sources) + 1}")
            if not any(node["id"] == source_id for node in nodes):
                nodes.append({"id": source_id, "label": source, "group": "source"})
            item_id = f"item:{item['id']}"
            nodes.append({"id": item_id, "label": item["title"][:28], "group": "item"})
            edges.append({"source": source_id, "target": item_id, "label": "采集"})
        return {"nodes": nodes, "edges": edges}

    @staticmethod
    def collection_by_source(limit: int = 10) -> list[dict]:
        """按数据源统计采集数量。"""
        limit = min(20, max(1, int(limit)))
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT s.name AS label, COUNT(r.id) AS value
                FROM lookout_sources s
                LEFT JOIN collection_rules r ON r.source_id = s.id
                LEFT JOIN collection_runs cr ON cr.rule_id = r.id
                WHERE s.enabled = 1
                GROUP BY s.id, s.name
                ORDER BY value DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{"label": str(row["label"]), "value": int(row["value"])} for row in rows]

    @staticmethod
    def daily_collection_count() -> list[dict]:
        """过去7天的日采集数量。"""
        with connection_scope() as connection:
            rows = connection.execute(
                """
                WITH RECURSIVE dates(day, remaining) AS (
                    SELECT date('now', '-6 day'), 7
                    UNION ALL
                    SELECT date(day, '+1 day'), remaining - 1 FROM dates WHERE remaining > 1
                )
                SELECT dates.day AS label,
                       COUNT(cr.id) AS value
                FROM dates
                LEFT JOIN collection_runs cr ON substr(cr.created_at, 1, 10) = dates.day
                GROUP BY dates.day
                ORDER BY dates.day
                """
            ).fetchall()
        return [{"label": str(row["label"]), "value": int(row["value"])} for row in rows]

    @staticmethod
    def risk_level_distribution() -> list[dict]:
        """按风险等级分布统计。"""
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT risk_level AS label, COUNT(*) AS value
                FROM warehouse_items
                GROUP BY risk_level
                ORDER BY CASE risk_level
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'normal' THEN 3
                    WHEN 'low' THEN 4
                END
                """
            ).fetchall()
        return [{"label": str(row["label"]), "value": int(row["value"])} for row in rows]

    @staticmethod
    def high_risk_items(limit: int = 20) -> list[dict]:
        """获取高风险项目。"""
        limit = min(50, max(1, int(limit)))
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT id, title, url, risk_level, source_name, created_at
                FROM warehouse_items
                WHERE risk_level IN ('high', 'critical')
                ORDER BY
                    CASE risk_level WHEN 'critical' THEN 1 WHEN 'high' THEN 2 END,
                    id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "title": str(row["title"]),
                "url": str(row["url"]),
                "risk_level": str(row["risk_level"]),
                "source": str(row["source_name"] or "未标注"),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    @staticmethod
    def keyword_frequency(limit: int = 20) -> list[dict]:
        """关键词频率统计。"""
        limit = min(50, max(1, int(limit)))
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT keywords AS label, COUNT(*) AS value
                FROM warehouse_items
                WHERE keywords <> ''
                GROUP BY keywords
                ORDER BY value DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{"label": str(row["label"]), "value": int(row["value"])} for row in rows]

    @staticmethod
    def source_performance() -> list[dict]:
        """数据源采集性能统计（平均耗时、成功率）。"""
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT
                    s.name AS label,
                    ROUND(AVG(
                        CASE
                            WHEN cr.finished_at IS NOT NULL
                            THEN (julianday(cr.finished_at) - julianday(cr.created_at)) * 86400
                            ELSE 0
                        END
                    ), 2) AS avg_time,
                    COUNT(CASE WHEN cr.status = 'success' THEN 1 END) AS success_count,
                    COUNT(cr.id) AS total_count
                FROM lookout_sources s
                LEFT JOIN collection_rules r ON r.source_id = s.id
                LEFT JOIN collection_runs cr ON cr.rule_id = r.id
                WHERE s.enabled = 1 AND cr.id IS NOT NULL
                GROUP BY s.id, s.name
                ORDER BY success_count DESC
                """
            ).fetchall()
        return [
            {
                "label": str(row["label"]),
                "avg_time": float(row["avg_time"] or 0),
                "success_count": int(row["success_count"] or 0),
                "total_count": int(row["total_count"] or 0),
                "success_rate": round(
                    (int(row["success_count"] or 0) / int(row["total_count"] or 1)) * 100, 2
                ),
            }
            for row in rows
        ]
