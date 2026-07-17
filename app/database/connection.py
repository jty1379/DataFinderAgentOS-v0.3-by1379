"""SQLite / SQLCipher 连接和事务生命周期管理。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

try:  # SQLCipher 驱动（提供整库 AES-256 加密）；缺失时回退到明文 sqlite3。
    from sqlcipher3 import dbapi2 as _sqlcipher
except Exception:  # pragma: no cover - 环境未安装 SQLCipher 时的降级路径
    _sqlcipher = None


def _apply_key(connection, key: str) -> None:
    """在任何其他语句之前提供密钥，否则 SQLCipher 会拒绝后续操作。"""
    # 密钥由 secrets.token_urlsafe 生成（仅 [A-Za-z0-9_-]），不含引号，可安全内联。
    connection.execute(f"PRAGMA key = '{key}'")


def open_connection(database_path: Path | str, key: str = "") -> sqlite3.Connection:
    """打开带外键、WAL 和忙等待配置的连接；提供 key 时启用 SQLCipher 整库加密。"""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if key and _sqlcipher is not None:
        connection = _sqlcipher.connect(path, timeout=5)
        connection.row_factory = _sqlcipher.Row
        _apply_key(connection, key)
    else:
        connection = sqlite3.connect(path, timeout=5)
        connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextmanager
def managed_connection(
    database_path: Path | str, key: str = ""
) -> Iterator[sqlite3.Connection]:
    """发生异常时回滚并始终关闭连接，避免 Windows 文件锁。"""
    connection = open_connection(database_path, key)
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
