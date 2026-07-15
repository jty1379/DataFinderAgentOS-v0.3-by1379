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
