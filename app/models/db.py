"""数据库兼容门面。

旧 Repository 继续从本模块取得连接；实际实现已拆分到 ``app.database``。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.database.connection import managed_connection, open_connection
from app.database.migration_runner import run_migrations
from app.database.seed import seed_database
from config.settings import SETTINGS
from config.settings import DATABASE_PATH as CONFIG_DATABASE_PATH

# 保留可替换模块变量，兼容现有临时数据库测试夹具。
DATABASE_PATH = CONFIG_DATABASE_PATH


def _active_key() -> str:
    """仅对配置指向的真实库启用加密；测试夹具改用临时库路径时自动走明文。"""
    try:
        return SETTINGS.database_key if Path(DATABASE_PATH) == SETTINGS.database_path else ""
    except Exception:
        return ""


def get_connection() -> sqlite3.Connection:
    return open_connection(DATABASE_PATH, _active_key())


@contextmanager
def connection_scope() -> Iterator[sqlite3.Connection]:
    with managed_connection(DATABASE_PATH, _active_key()) as connection:
        yield connection


def init_db() -> None:
    """迁移数据库并幂等写入运行所需种子数据。"""
    run_migrations(get_connection)
    with connection_scope() as connection:
        seed_database(connection)
        connection.commit()
