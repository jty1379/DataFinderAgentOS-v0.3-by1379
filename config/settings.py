"""集中管理应用配置，避免在入口和 Controller 中硬编码。"""

from __future__ import annotations

import os
import secrets
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
APP_PORT = int(os.getenv("DATAFINDER_PORT", "10010"))
DEBUG = os.getenv("DATAFINDER_DEBUG", "0").strip().lower() in {"1", "true", "yes"}
DATABASE_PATH = Path(
    os.getenv("DATAFINDER_DB_PATH", str(BASE_DIR / "database" / "finderos.db"))
).resolve()
COOKIE_SECRET_FILE = Path(
    os.getenv(
        "DATAFINDER_COOKIE_SECRET_FILE",
        str(BASE_DIR / "config" / "runtime_secret.txt"),
    )
).resolve()

# 未来接入大模型时只允许从配置层读取，不允许 Controller 直连 SDK。
LLM_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_BASE_URL = os.getenv("OPENAI_BASE_URL", "")
LLM_MODEL = os.getenv("DATAFINDER_LLM_MODEL", "")


def load_cookie_secret() -> str:
    """优先读取环境变量，否则生成并持久化本机运行密钥。"""
    value = os.getenv("DATAFINDER_COOKIE_SECRET", "").strip()
    if value:
        return value

    if COOKIE_SECRET_FILE.exists():
        saved = COOKIE_SECRET_FILE.read_text(encoding="utf-8").strip()
        if saved:
            return saved

    COOKIE_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    generated = secrets.token_urlsafe(48)
    COOKIE_SECRET_FILE.write_text(generated, encoding="utf-8")
    return generated


COOKIE_SECRET = load_cookie_secret()
