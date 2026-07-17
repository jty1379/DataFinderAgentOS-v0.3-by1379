"""按运行环境加载并校验应用启动配置的唯一入口。"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from config.development import DEFAULTS as DEVELOPMENT_DEFAULTS
from config.production import DEFAULTS as PRODUCTION_DEFAULTS
from config.testing import DEFAULTS as TESTING_DEFAULTS

BASE_DIR = Path(__file__).resolve().parent.parent
PROFILES = {
    "development": DEVELOPMENT_DEFAULTS,
    "testing": TESTING_DEFAULTS,
    "production": PRODUCTION_DEFAULTS,
}


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _value(name: str, legacy_name: str | None = None, default: str = "") -> str:
    """兼容旧变量名；所有环境读取均收口在本模块。"""
    return os.environ.get(name, os.environ.get(legacy_name, default) if legacy_name else default)


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str
    debug: bool
    host: str
    port: int
    database_path: Path
    cookie_secret_file: Path
    cookie_secret: str
    database_key_file: Path
    database_key: str
    xsrf_cookies: bool
    log_level: str
    log_dir: Path
    model_api_key_env: str
    collection_timeout_seconds: int
    response_size_limit: int
    upload_size_limit: int
    system_name: str
    default_model: str
    open_registration: bool

    def secret_from_env(self, variable_name: str) -> str:
        """按数据库记录的变量名读取密钥，但不向业务层暴露 environ。"""
        if not variable_name:
            return ""
        return os.environ.get(variable_name, "").strip()

    def public_summary(self) -> dict[str, object]:
        """仅返回可安全写入启动日志的非敏感配置。"""
        return {
            "app_env": self.app_env,
            "debug": self.debug,
            "host": self.host,
            "port": self.port,
            "database_path": str(self.database_path),
            "xsrf_cookies": self.xsrf_cookies,
            "log_level": self.log_level,
        }


def _cookie_secret(app_env: str, secret_file: Path) -> str:
    explicit = _value("COOKIE_SECRET", "DATAFINDER_COOKIE_SECRET").strip()
    if explicit:
        if len(explicit) < 32:
            raise RuntimeError("COOKIE_SECRET 至少需要 32 个字符")
        return explicit
    if secret_file.exists():
        saved = secret_file.read_text(encoding="utf-8").strip()
        if len(saved) >= 32:
            return saved
    if app_env == "production":
        raise RuntimeError("生产环境必须通过 COOKIE_SECRET 或密钥文件提供至少 32 位密钥")
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    generated = secrets.token_urlsafe(48)
    secret_file.write_text(generated, encoding="utf-8")
    return generated


def _database_key(app_env: str, key_file: Path) -> str:
    """数据库文件加密密钥：环境变量优先，其次密钥文件；均不入库、不进代码。"""
    explicit = _value("DATABASE_KEY", "DATAFINDER_DB_KEY").strip()
    if explicit:
        if len(explicit) < 16:
            raise RuntimeError("DATABASE_KEY 至少需要 16 个字符")
        return explicit
    if key_file.exists():
        saved = key_file.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    if app_env == "testing":
        return ""
    if app_env == "production":
        raise RuntimeError("生产环境必须通过 DATABASE_KEY 或密钥文件提供数据库加密密钥")
    key_file.parent.mkdir(parents=True, exist_ok=True)
    generated = secrets.token_urlsafe(48)
    key_file.write_text(generated, encoding="utf-8")
    return generated


def load_settings() -> Settings:
    app_env = _value("APP_ENV", default="development").strip().lower()
    if app_env not in PROFILES:
        raise RuntimeError("APP_ENV 只能是 development、testing 或 production")
    defaults = PROFILES[app_env]
    debug = _bool(_value("DEBUG", "DATAFINDER_DEBUG", str(defaults["debug"])))
    if app_env == "production" and debug:
        raise RuntimeError("生产环境禁止开启 DEBUG")
    database_path = Path(_value("DATABASE_PATH", "DATAFINDER_DB_PATH", str(defaults["database_path"]))).resolve()
    secret_file = Path(_value("COOKIE_SECRET_FILE", "DATAFINDER_COOKIE_SECRET_FILE", str(BASE_DIR / "config" / "runtime_secret.txt"))).resolve()
    db_key_file = Path(_value("DATABASE_KEY_FILE", "DATAFINDER_DB_KEY_FILE", str(BASE_DIR / "config" / "db_secret.key"))).resolve()
    return Settings(
        app_env=app_env,
        debug=debug,
        host=_value("HOST", default=str(defaults["host"])),
        port=int(_value("PORT", "DATAFINDER_PORT", str(defaults["port"]))),
        database_path=database_path,
        cookie_secret_file=secret_file,
        cookie_secret=_cookie_secret(app_env, secret_file),
        database_key_file=db_key_file,
        database_key=_database_key(app_env, db_key_file),
        xsrf_cookies=_bool(_value("XSRF_COOKIES", default="true")),
        log_level=_value("LOG_LEVEL", default="INFO").upper(),
        log_dir=Path(_value("LOG_DIR", default=str(BASE_DIR / "logs"))).resolve(),
        model_api_key_env=_value("MODEL_API_KEY_ENV", default="OPENAI_API_KEY"),
        collection_timeout_seconds=int(_value("COLLECTION_TIMEOUT_SECONDS", default="20")),
        response_size_limit=int(_value("RESPONSE_SIZE_LIMIT", default=str(5 * 1024 * 1024))),
        upload_size_limit=int(_value("UPLOAD_SIZE_LIMIT", default=str(10 * 1024 * 1024))),
        system_name=_value("SYSTEM_NAME", default="瞭望与问数系统"),
        default_model=_value("DEFAULT_MODEL", "DATAFINDER_LLM_MODEL"),
        open_registration=_bool(_value("OPEN_REGISTRATION", default="true")),
    )


SETTINGS = load_settings()

# 兼容现有模块；新代码应优先使用 SETTINGS。
APP_PORT = SETTINGS.port
DEBUG = SETTINGS.debug
DATABASE_PATH = SETTINGS.database_path
COOKIE_SECRET_FILE = SETTINGS.cookie_secret_file
COOKIE_SECRET = SETTINGS.cookie_secret
LLM_API_KEY = SETTINGS.secret_from_env(SETTINGS.model_api_key_env)
LLM_BASE_URL = _value("OPENAI_BASE_URL")
LLM_MODEL = SETTINGS.default_model
