"""数据仓库 Repository。"""

from __future__ import annotations

import json

from app.models.db import connection_scope


def _item(row) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    try:
        result["raw_data"] = json.loads(result.get("raw_data") or "{}")
    except json.JSONDecodeError:
        result["raw_data"] = {}
    try:
        result["security_analysis"] = json.loads(result.get("security_analysis") or "{}")
    except json.JSONDecodeError:
        result["security_analysis"] = {}
    result["deep_collected"] = bool(result["deep_collected"])
    result["risk_level"] = str(result.get("risk_level", "normal"))
    result["keywords"] = str(result.get("keywords", ""))
    result["matched_words"] = str(result.get("matched_words", ""))
    return result


class WarehouseRepository:
    @staticmethod
    def get_by_source_result_id(result_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                "SELECT * FROM warehouse_items WHERE source_result_id=?", (int(result_id),)
            ).fetchone()
        return _item(row)

    @staticmethod
    def import_results(result_ids, user_id: int | None) -> tuple[int, int]:
        ids: list[int] = []
        for value in result_ids or []:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0 and parsed not in ids:
                ids.append(parsed)
        if not ids:
            return 0, 0

        inserted = 0
        with connection_scope() as connection:
            for result_id in ids[:200]:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO warehouse_items
                        (source_result_id, rule_id, title, url, summary, source_name,
                         published_at, raw_data, created_by)
                    SELECT id, rule_id, title, url, summary, source_name,
                           published_at, raw_data, ?
                    FROM collection_results r
                    WHERE r.id = ?
                      AND NOT EXISTS (
                          SELECT 1 FROM warehouse_items w
                          WHERE w.source_result_id = r.id OR w.url = r.url
                      )
                    """,
                    (user_id, result_id),
                )
                inserted += max(0, cursor.rowcount)
            connection.commit()
        return inserted, len(ids[:200]) - inserted

    @staticmethod
    def list(
        keyword: str = "",
        deep_status: str = "",
        source_name: str = "",
        risk_level: str = "",
        start_date: str = "",
        end_date: str = "",
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[dict], int]:
        page = max(1, int(page or 1))
        page_size = min(100, max(1, int(page_size or 10)))
        offset = (page - 1) * page_size
        keyword = keyword.strip()
        pattern = f"%{keyword}%"
        clauses = ["(? = '' OR w.title LIKE ? OR w.summary LIKE ? OR w.source_name LIKE ?)"]
        params: list[object] = [keyword, pattern, pattern, pattern]
        normalized_status = deep_status.strip().lower()
        if normalized_status in {"1", "yes", "true", "deep", "completed"}:
            clauses.append("w.deep_collected = 1")
        elif normalized_status in {"0", "no", "false", "pending"}:
            clauses.append("w.deep_collected = 0")
        source_name = source_name.strip()
        if source_name:
            clauses.append("w.source_name = ?")
            params.append(source_name)
        if risk_level in {"low", "normal", "high", "critical"}:
            clauses.append("w.risk_level = ?")
            params.append(risk_level)
        if start_date:
            clauses.append("date(w.created_at) >= date(?)")
            params.append(start_date)
        if end_date:
            clauses.append("date(w.created_at) <= date(?)")
            params.append(end_date)
        where = " AND ".join(clauses)
        with connection_scope() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM warehouse_items w WHERE " + where,
                    params,
                ).fetchone()["count"]
            )
            rows = connection.execute(
                """
                SELECT w.*, u.username AS creator_name, r.name AS rule_name
                FROM warehouse_items w
                LEFT JOIN users u ON u.id = w.created_by
                LEFT JOIN collection_rules r ON r.id = w.rule_id
                WHERE """
                + where
                + " ORDER BY w.id DESC LIMIT ? OFFSET ?",
                (*params, page_size, offset),
            ).fetchall()
        return [_item(row) for row in rows], total

    @staticmethod
    def source_names() -> list[str]:
        with connection_scope() as connection:
            rows = connection.execute(
                """SELECT DISTINCT source_name FROM warehouse_items
                   WHERE source_name<>'' ORDER BY source_name"""
            ).fetchall()
        return [str(row["source_name"]) for row in rows]

    @staticmethod
    def export_rows(
        *,
        keyword: str = "",
        deep_status: str = "",
        source_name: str = "",
        risk_level: str = "",
        start_date: str = "",
        end_date: str = "",
        limit: int = 5000,
    ) -> list[dict]:
        maximum = min(5000, max(1, int(limit)))
        output: list[dict] = []
        page = 1
        while len(output) < maximum:
            rows, total = WarehouseRepository.list(
                keyword=keyword,
                deep_status=deep_status,
                source_name=source_name,
                risk_level=risk_level,
                start_date=start_date,
                end_date=end_date,
                page=page,
                page_size=100,
            )
            output.extend(rows)
            if not rows or len(output) >= total:
                break
            page += 1
        return output[:maximum]

    @staticmethod
    def recollection_context(item_id: int) -> dict | None:
        with connection_scope() as connection:
            row = connection.execute(
                """SELECT w.id,w.rule_id,w.title,w.source_name,
                          COALESCE(cr.keyword,w.title) AS keyword,
                          COALESCE(cr.page_number,1) AS page_number,
                          COALESCE(cr.page_size,12) AS page_size
                   FROM warehouse_items w
                   LEFT JOIN collection_results result ON result.id=w.source_result_id
                   LEFT JOIN collection_runs cr ON cr.id=result.run_id
                   WHERE w.id=?""",
                (int(item_id),),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get(item_id: int):
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT w.*, u.username AS creator_name, r.name AS rule_name
                FROM warehouse_items w
                LEFT JOIN users u ON u.id = w.created_by
                LEFT JOIN collection_rules r ON r.id = w.rule_id
                WHERE w.id = ?
                """,
                (item_id,),
            ).fetchone()
        return _item(row)

    @staticmethod
    def delete(item_id: int) -> bool:
        with connection_scope() as connection:
            cursor = connection.execute("DELETE FROM warehouse_items WHERE id = ?", (item_id,))
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def set_deep_collected(item_id: int, completed: bool, content: str = "") -> bool:
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                UPDATE warehouse_items
                SET deep_collected = ?, content = CASE WHEN ? <> '' THEN ? ELSE content END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (int(bool(completed)), content, content[:100000], item_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def batch_delete(item_ids: list[int]) -> int:
        """批量删除仓库项。

        Args:
            item_ids: 仓库项ID列表

        Returns:
            删除的项数
        """
        if not item_ids:
            return 0
        ids = item_ids[:1000]  # 限制最多1000条
        placeholders = ",".join("?" * len(ids))
        with connection_scope() as connection:
            cursor = connection.execute(
                f"DELETE FROM warehouse_items WHERE id IN ({placeholders})", ids
            )
            connection.commit()
        return cursor.rowcount

    @staticmethod
    def update_risk_level(item_id: int, risk_level: str, security_analysis: dict | None = None) -> bool:
        """更新项目风险等级和舆情分析结果。

        Args:
            item_id: 仓库项ID
            risk_level: 风险等级 ('low', 'normal', 'high', 'critical')
            security_analysis: 舆情分析结果字典

        Returns:
            是否成功更新
        """
        if risk_level not in ("low", "normal", "high", "critical"):
            risk_level = "normal"

        analysis_json = "{}"
        if security_analysis:
            try:
                analysis_json = json.dumps(security_analysis, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                analysis_json = "{}"

        with connection_scope() as connection:
            cursor = connection.execute(
                """
                UPDATE warehouse_items
                SET risk_level = ?, security_analysis = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (risk_level, analysis_json, item_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def update_keywords(item_id: int, keywords: str, matched_words: str = "") -> bool:
        """更新项目关键词和匹配词汇。

        Args:
            item_id: 仓库项ID
            keywords: 关键词字符串
            matched_words: 匹配的敏感词

        Returns:
            是否成功更新
        """
        with connection_scope() as connection:
            cursor = connection.execute(
                """
                UPDATE warehouse_items
                SET keywords = ?, matched_words = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (keywords[:500], matched_words[:500], item_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def get_duplicates(title: str, url: str) -> list[dict]:
        """检查重复的仓库项。

        Args:
            title: 标题
            url: URL

        Returns:
            重复项列表
        """
        with connection_scope() as connection:
            # 完全匹配或相似度较高
            rows = connection.execute(
                """
                SELECT * FROM warehouse_items
                WHERE (url = ? OR title = ?)
                ORDER BY id DESC LIMIT 10
                """,
                (url, title),
            ).fetchall()
        return [_item(row) for row in rows]

    @staticmethod
    def deduplication() -> int:
        """执行数据去重，删除重复的URL。

        Returns:
            删除的项数
        """
        with connection_scope() as connection:
            # 找出每个URL的最新版本
            cursor = connection.execute(
                """
                DELETE FROM warehouse_items
                WHERE id NOT IN (
                    SELECT MAX(id) FROM warehouse_items GROUP BY url
                )
                """
            )
            connection.commit()
        return cursor.rowcount

    @staticmethod
    def get_by_risk_level(risk_level: str, limit: int = 50) -> list[dict]:
        """按风险等级获取仓库项。

        Args:
            risk_level: 风险等级
            limit: 限制数量

        Returns:
            仓库项列表
        """
        limit = min(200, max(1, int(limit)))
        with connection_scope() as connection:
            rows = connection.execute(
                """
                SELECT w.*, u.username AS creator_name, r.name AS rule_name
                FROM warehouse_items w
                LEFT JOIN users u ON u.id = w.created_by
                LEFT JOIN collection_rules r ON r.id = w.rule_id
                WHERE w.risk_level = ?
                ORDER BY w.id DESC LIMIT ?
                """,
                (risk_level, limit),
            ).fetchall()
        return [_item(row) for row in rows]

    @staticmethod
    def get_summary_stats() -> dict:
        """获取仓库统计摘要。

        Returns:
            统计字典
        """
        with connection_scope() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) as total_count,
                    SUM(CASE WHEN deep_collected=1 THEN 1 ELSE 0 END) as deep_count,
                    SUM(CASE WHEN risk_level='critical' THEN 1 ELSE 0 END) as critical_count,
                    SUM(CASE WHEN risk_level='high' THEN 1 ELSE 0 END) as high_count,
                    SUM(CASE WHEN risk_level='normal' THEN 1 ELSE 0 END) as normal_count,
                    SUM(CASE WHEN risk_level='low' THEN 1 ELSE 0 END) as low_count
                FROM warehouse_items
                """
            ).fetchone()
        return {
            "total_count": int(row["total_count"] or 0),
            "deep_count": int(row["deep_count"] or 0),
            "critical_count": int(row["critical_count"] or 0),
            "high_count": int(row["high_count"] or 0),
            "normal_count": int(row["normal_count"] or 0),
            "low_count": int(row["low_count"] or 0),
        }
