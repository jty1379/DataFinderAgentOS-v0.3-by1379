"""SQLite 连接和事务生命周期管理。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def open_connection(database_path: Path | str) -> sqlite3.Connection:
    """打开带外键、WAL 和忙等待配置的 SQLite 连接。"""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextmanager
def managed_connection(database_path: Path | str) -> Iterator[sqlite3.Connection]:
    """发生异常时回滚并始终关闭连接，避免 Windows 文件锁。"""
    connection = open_connection(database_path)
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
