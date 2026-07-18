"""带滚动文件、请求字段默认值和日志分类的统一日志配置。"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.settings import Settings

FORMAT = "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s user_id=%(user_id)s task_id=%(task_id)s event=%(event)s %(message)s"


_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]+")


def single_line_log_value(value, max_length: int = 512) -> str:
    """Return one bounded log-safe line for data derived from a request.

    Plain-text log handlers treat CR/LF and other control characters as record
    separators.  Replacing them before formatting prevents a request path,
    header or audit field from forging additional log entries.
    """
    text = _CONTROL_CHARACTERS.sub(" ", str(value or ""))
    return " ".join(text.split())[: max(1, int(max_length))]


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for name in ("request_id", "user_id", "task_id", "event"):
            if not hasattr(record, name):
                setattr(record, name, "-")
        return True


class ErrorFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.ERROR


def _handler(path: Path, level: int, extra_filter: logging.Filter | None = None) -> RotatingFileHandler:
    handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(FORMAT))
    handler.addFilter(ContextFilter())
    if extra_filter:
        handler.addFilter(extra_filter)
    return handler


def configure_logging(settings: Settings) -> None:
    """初始化一次日志体系，不输出密钥、密码或 Cookie。"""
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level, logging.INFO))
    root.handlers.clear()
    root.addHandler(_handler(settings.log_dir / "app.log", logging.INFO))
    root.addHandler(_handler(settings.log_dir / "error.log", logging.ERROR, ErrorFilter()))
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(FORMAT))
    console.addFilter(ContextFilter())
    root.addHandler(console)
    for logger_name, file_name in {
        "security": "security.log",
        "collection": "collection.log",
        "model": "model.log",
        "audit": "audit.log",
        "migration": "migration.log",
    }.items():
        logger = logging.getLogger(logger_name)
        logger.addHandler(_handler(settings.log_dir / file_name, logging.INFO))
