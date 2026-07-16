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
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
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
            try:
                connection.execute("BEGIN IMMEDIATE")
                for statement in _sql_statements(script):
                    connection.execute(statement)
                if version == 1:
                    _ensure_legacy_columns(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, description, checksum) VALUES (?, ?, ?, ?)",
                    (version, name, name.replace("_", " "), checksum),
                )
                connection.commit()
            except sqlite3.Error as exc:
                connection.rollback()
                LOGGER.exception("migration failed version=%s name=%s", version, name)
                raise MigrationError(f"迁移 {path.name} 执行失败并已回滚") from exc
            LOGGER.info("migration applied version=%s name=%s", version, name)
    finally:
        connection.close()
