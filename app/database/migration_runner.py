"""按版本、名称和校验和执行一次性 SQLite 迁移。"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path

LOGGER = logging.getLogger("migration")
MIGRATION_PATTERN = re.compile(r"^(?P<version>\d+)_(?P<name>[a-z0-9_]+)\.sql$")
MIGRATIONS_DIR = Path(__file__).with_name("migrations")


class MigrationError(RuntimeError):
    """数据库迁移无法安全完成。"""


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _add_column_if_missing(
    connection: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    if column not in _table_columns(connection, table):
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_employee_stats(connection: sqlite3.Connection) -> None:
    _add_column_if_missing(connection, "digital_employees", "call_count", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(connection, "digital_employees", "failure_count", "INTEGER NOT NULL DEFAULT 0")


def _migrate_warehouse_extensions(connection: sqlite3.Connection) -> None:
    _add_column_if_missing(
        connection, "warehouse_items", "keywords", "TEXT NOT NULL DEFAULT '' CHECK (length(keywords) <= 500)"
    )
    _add_column_if_missing(
        connection,
        "warehouse_items",
        "risk_level",
        "TEXT NOT NULL DEFAULT 'normal' CHECK (risk_level IN ('low', 'normal', 'high', 'critical'))",
    )
    _add_column_if_missing(
        connection,
        "warehouse_items",
        "matched_words",
        "TEXT NOT NULL DEFAULT '' CHECK (length(matched_words) <= 500)",
    )
    _add_column_if_missing(
        connection, "warehouse_items", "security_analysis", "TEXT NOT NULL DEFAULT '{}'"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_warehouse_risk_level ON warehouse_items(risk_level)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_warehouse_keywords ON warehouse_items(keywords)")


def _create_system_settings_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS system_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_key TEXT NOT NULL UNIQUE,
            setting_value TEXT NOT NULL DEFAULT '',
            setting_type TEXT NOT NULL DEFAULT 'string'
                CHECK (setting_type IN ('string', 'integer', 'boolean', 'float', 'json')),
            description TEXT NOT NULL DEFAULT '',
            is_sensitive INTEGER NOT NULL DEFAULT 0 CHECK (is_sensitive IN (0,1)),
            updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _migrate_system_settings_biometrics(connection: sqlite3.Connection) -> None:
    """统一 A 的系统设置与 D 的生物识别表，并兼容两种旧表结构。"""
    if _table_exists(connection, "system_settings"):
        columns = _table_columns(connection, "system_settings")
        if not {"setting_key", "setting_value"}.issubset(columns):
            if not {"key", "value"}.issubset(columns):
                raise MigrationError("system_settings 表结构无法识别，已停止自动升级")
            rows = [dict(row) for row in connection.execute("SELECT * FROM system_settings")]
            connection.execute("ALTER TABLE system_settings RENAME TO system_settings_legacy_20")
            _create_system_settings_table(connection)
            for row in rows:
                key = "enable_face_login" if row["key"] == "face_login_enabled" else row["key"]
                value = "true" if key == "enable_face_login" and str(row["value"]) == "1" else str(row["value"])
                connection.execute(
                    """INSERT OR IGNORE INTO system_settings
                       (setting_key,setting_value,setting_type,description,is_sensitive,updated_by,updated_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        key,
                        value,
                        "boolean" if key == "enable_face_login" else "string",
                        "是否启用人脸登录" if key == "enable_face_login" else "",
                        0,
                        row.get("updated_by"),
                        row.get("updated_at") or "",
                    ),
                )
            connection.execute("DROP TABLE system_settings_legacy_20")
    else:
        _create_system_settings_table(connection)

    connection.execute("CREATE INDEX IF NOT EXISTS ix_settings_key ON system_settings(setting_key)")
    legacy_face = connection.execute(
        "SELECT setting_value FROM system_settings WHERE setting_key='face_login_enabled'"
    ).fetchone()
    if legacy_face:
        connection.execute(
            """INSERT OR IGNORE INTO system_settings
               (setting_key,setting_value,setting_type,description)
               VALUES ('enable_face_login',?,'boolean','是否启用人脸登录')""",
            ("true" if str(legacy_face["setting_value"]).lower() in {"1", "true", "yes", "on"} else "false",),
        )
        connection.execute("DELETE FROM system_settings WHERE setting_key='face_login_enabled'")
    connection.execute(
        """INSERT OR IGNORE INTO system_settings
           (setting_key,setting_value,setting_type,description)
           VALUES ('enable_face_login','true','boolean','是否启用人脸登录')"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS face_profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            embedding TEXT NOT NULL,
            sample_count INTEGER NOT NULL DEFAULT 0 CHECK (sample_count >= 3),
            enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
            liveness_method TEXT NOT NULL DEFAULT 'multi_frame_motion',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS gesture_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            gesture TEXT NOT NULL CHECK (gesture IN ('victory', 'fist', 'open_palm')),
            action TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 1),
            triggered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_face_profiles_enabled ON face_profiles(enabled)")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_gesture_events_user_time ON gesture_events(user_id, triggered_at DESC)"
    )
    connection.execute("UPDATE features SET route='/admin/screens/intelligence' WHERE code='intelligence_screen'")
    connection.execute("UPDATE features SET route='/admin/screens/opinion' WHERE code='opinion_screen'")


def _create_opinion_alerts_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS opinion_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL DEFAULT 'chat'
                CHECK (source_type IN ('chat', 'collection', 'employee', 'news')),
            source_id INTEGER,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            excerpt TEXT NOT NULL DEFAULT '',
            matched_words TEXT NOT NULL DEFAULT '[]',
            risk_level TEXT NOT NULL DEFAULT 'low'
                CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
            ai_analysis TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'processing', 'resolved', 'false_positive')),
            handled_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            handle_note TEXT NOT NULL DEFAULT '',
            handled_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )


def _migrate_opinion_security(connection: sqlite3.Connection) -> None:
    """把 D 的大屏预警结构升级为 A 的管理结构，并保留展示字段。"""
    if _table_exists(connection, "opinion_alerts"):
        columns = _table_columns(connection, "opinion_alerts")
        if "sensitive_words" in columns or "handler_note" in columns:
            rows = [dict(row) for row in connection.execute("SELECT * FROM opinion_alerts")]
            connection.execute("ALTER TABLE opinion_alerts RENAME TO opinion_alerts_legacy_21")
            _create_opinion_alerts_table(connection)
            for row in rows:
                connection.execute(
                    """INSERT INTO opinion_alerts
                       (id,source_type,source_id,user_id,title,content,excerpt,matched_words,
                        risk_level,ai_analysis,status,handled_by,handle_note,handled_at,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row["id"],
                        "chat" if row.get("source_type") == "user_message" else row.get("source_type", "chat"),
                        row.get("source_id"),
                        row.get("user_id"),
                        row.get("title", ""),
                        row.get("content") or row.get("excerpt") or row.get("title", ""),
                        row.get("excerpt") or str(row.get("content") or "")[:500],
                        row.get("matched_words") or row.get("sensitive_words") or "[]",
                        row.get("risk_level", "low"),
                        row.get("ai_analysis", ""),
                        "pending" if row.get("status") == "new" else row.get("status", "pending"),
                        row.get("handled_by"),
                        row.get("handle_note") or row.get("handler_note") or "",
                        row.get("handled_at"),
                        row.get("created_at") or "",
                        row.get("updated_at") or row.get("created_at") or "",
                    ),
                )
            connection.execute("DROP TABLE opinion_alerts_legacy_21")
        else:
            _add_column_if_missing(connection, "opinion_alerts", "title", "TEXT NOT NULL DEFAULT ''")
            _add_column_if_missing(connection, "opinion_alerts", "excerpt", "TEXT NOT NULL DEFAULT ''")
            _add_column_if_missing(connection, "opinion_alerts", "updated_at", "TEXT NOT NULL DEFAULT ''")
            connection.execute(
                "UPDATE opinion_alerts SET updated_at=created_at WHERE updated_at='' OR updated_at IS NULL"
            )
    else:
        _create_opinion_alerts_table(connection)

    connection.execute(
        """CREATE TABLE IF NOT EXISTS sensitive_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL DEFAULT 'default',
            level INTEGER NOT NULL DEFAULT 1 CHECK (level IN (1,2,3,4)),
            description TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS opinion_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER NOT NULL REFERENCES opinion_alerts(id) ON DELETE CASCADE,
            analysis_type TEXT NOT NULL DEFAULT 'sentiment'
                CHECK (analysis_type IN ('sentiment', 'topic', 'risk')),
            result TEXT NOT NULL DEFAULT '{}',
            confidence REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id INTEGER,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            user_name TEXT NOT NULL DEFAULT '',
            ip_address TEXT NOT NULL DEFAULT '',
            action_before TEXT NOT NULL DEFAULT '{}',
            action_after TEXT NOT NULL DEFAULT '{}',
            detail TEXT NOT NULL DEFAULT '',
            success INTEGER NOT NULL DEFAULT 1 CHECK (success IN (0,1)),
            error_message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.execute("CREATE INDEX IF NOT EXISTS ix_sensitive_words_word ON sensitive_words(word)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_opinion_alerts_status ON opinion_alerts(status,created_at DESC)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_opinion_alerts_risk ON opinion_alerts(risk_level,created_at DESC)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_opinion_alerts_user ON opinion_alerts(user_id,created_at DESC)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_opinion_alerts_source ON opinion_alerts(source_type,source_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_user ON audit_logs(user_id,created_at DESC)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_action ON audit_logs(action_type,created_at DESC)")


def _migrate_warehouse_duplicate_support(connection: sqlite3.Connection) -> None:
    """移除早期 URL 唯一约束，让显式查重/批量去重流程能够处理历史重复数据。"""
    sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='warehouse_items'"
    ).fetchone()
    if not sql or "URL TEXT NOT NULL UNIQUE" not in str(sql["sql"]).upper():
        return
    connection.execute(
        """CREATE TABLE warehouse_items_v22 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_result_id INTEGER REFERENCES collection_results(id) ON DELETE SET NULL,
            rule_id INTEGER REFERENCES collection_rules(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            source_name TEXT NOT NULL DEFAULT '',
            published_at TEXT NOT NULL DEFAULT '',
            raw_data TEXT NOT NULL DEFAULT '{}',
            deep_collected INTEGER NOT NULL DEFAULT 0 CHECK (deep_collected IN (0,1)),
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            keywords TEXT NOT NULL DEFAULT '' CHECK (length(keywords) <= 500),
            risk_level TEXT NOT NULL DEFAULT 'normal'
                CHECK (risk_level IN ('low', 'normal', 'high', 'critical')),
            matched_words TEXT NOT NULL DEFAULT '' CHECK (length(matched_words) <= 500),
            security_analysis TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    columns = (
        "id,source_result_id,rule_id,title,url,summary,content,source_name,published_at,"
        "raw_data,deep_collected,created_by,created_at,updated_at,keywords,risk_level,"
        "matched_words,security_analysis"
    )
    connection.execute(
        f"INSERT INTO warehouse_items_v22({columns}) SELECT {columns} FROM warehouse_items"
    )
    connection.execute("DROP TABLE warehouse_items")
    connection.execute("ALTER TABLE warehouse_items_v22 RENAME TO warehouse_items")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_warehouse_created ON warehouse_items(created_at DESC)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_warehouse_deep ON warehouse_items(deep_collected,created_at DESC)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_warehouse_risk_level ON warehouse_items(risk_level)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_warehouse_keywords ON warehouse_items(keywords)")


PYTHON_MIGRATIONS = {
    17: _migrate_employee_stats,
    19: _migrate_warehouse_extensions,
    20: _migrate_system_settings_biometrics,
    21: _migrate_opinion_security,
    22: _migrate_warehouse_duplicate_support,
}


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            checksum TEXT NOT NULL DEFAULT ''
        )
        """
    )
    columns = _table_columns(connection, "schema_migrations")
    if "name" not in columns:
        connection.execute("ALTER TABLE schema_migrations ADD COLUMN name TEXT NOT NULL DEFAULT ''")
    if "checksum" not in columns:
        connection.execute("ALTER TABLE schema_migrations ADD COLUMN checksum TEXT NOT NULL DEFAULT ''")
    connection.commit()


def _sql_statements(script: str) -> list[str]:
    """用 SQLite 自身的完整语句判定拆分脚本，保留事务控制权。"""
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise MigrationError("迁移脚本末尾存在不完整 SQL")
    return statements


def _ensure_legacy_columns(connection: sqlite3.Connection) -> None:
    """让早期课堂数据库可在正式迁移接管前平滑升级。"""
    additions = {
        "users": {
            "role_id": "INTEGER REFERENCES roles(id)",
            "status": "TEXT NOT NULL DEFAULT 'enabled'",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
            "is_superadmin": "INTEGER NOT NULL DEFAULT 0 CHECK (is_superadmin IN (0, 1))",
        },
        "features": {"parent_id": "INTEGER REFERENCES features(id) ON DELETE RESTRICT"},
        "lookout_sources": {"code": "TEXT NOT NULL DEFAULT ''"},
        "model_configs": {"provider": "TEXT NOT NULL DEFAULT 'OpenAI Compatible'"},
    }
    for table, columns in additions.items():
        existing = _table_columns(connection, table)
        for column, definition in columns.items():
            if column not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def run_migrations(connection_factory: Callable[[], sqlite3.Connection]) -> None:
    """按版本执行迁移；校验和变化或执行失败时立即终止。"""
    connection = connection_factory()
    try:
        _ensure_migration_table(connection)
        applied = {
            int(row["version"]): row["checksum"]
            for row in connection.execute("SELECT version, checksum FROM schema_migrations")
        }
        paths = sorted(MIGRATIONS_DIR.glob("*.sql"))
        versions = [int(MIGRATION_PATTERN.match(path.name).group("version")) for path in paths if MIGRATION_PATTERN.match(path.name)]
        duplicates = sorted({version for version in versions if versions.count(version) > 1})
        if duplicates:
            raise MigrationError(f"迁移版本号重复: {', '.join(map(str, duplicates))}")
        for path in paths:
            match = MIGRATION_PATTERN.match(path.name)
            if not match:
                continue
            version = int(match.group("version"))
            name = match.group("name")
            script = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(script.encode("utf-8")).hexdigest()
            if version in applied:
                if applied[version] and applied[version] != checksum:
                    raise MigrationError(f"已执行迁移 {path.name} 的校验和发生变化")
                continue
            LOGGER.info("applying migration version=%s name=%s", version, name)
            disable_foreign_keys = version == 22
            try:
                if disable_foreign_keys:
                    connection.execute("PRAGMA foreign_keys=OFF")
                connection.execute("BEGIN IMMEDIATE")
                for statement in _sql_statements(script):
                    connection.execute(statement)
                python_migration = PYTHON_MIGRATIONS.get(version)
                if python_migration:
                    python_migration(connection)
                if version == 1:
                    _ensure_legacy_columns(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, description, checksum) VALUES (?, ?, ?, ?)",
                    (version, name, name.replace("_", " "), checksum),
                )
                connection.commit()
            except (sqlite3.Error, MigrationError) as exc:
                connection.rollback()
                LOGGER.exception("migration failed version=%s name=%s", version, name)
                raise MigrationError(f"迁移 {path.name} 执行失败并已回滚") from exc
            finally:
                if disable_foreign_keys:
                    connection.execute("PRAGMA foreign_keys=ON")
            LOGGER.info("migration applied version=%s name=%s", version, name)
    finally:
        connection.close()
