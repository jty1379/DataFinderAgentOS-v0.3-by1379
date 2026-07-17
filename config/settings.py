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


# 应用自身的敏感环境变量：禁止业务层经 secret_from_env 间接读取，
# 防止被配置为模型/TTS/多模态的 api_key_env 后随外部请求外泄。
_PROTECTED_ENV_NAMES = frozenset(
    {
        "COOKIE_SECRET",
        "DATAFINDER_COOKIE_SECRET",
        "COOKIE_SECRET_FILE",
        "DATAFINDER_COOKIE_SECRET_FILE",
        "DATABASE_KEY",
        "DATAFINDER_DB_KEY",
        "DATABASE_KEY_FILE",
        "DATAFINDER_DB_KEY_FILE",
        "ADMIN_INITIAL_PASSWORD",
        "DATAFINDER_ADMIN_PASSWORD",
        "DEV_ADMIN_PASSWORD",
        "SECRET_KEY",
    }
)


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
    initial_admin_password: str

    def secret_from_env(self, variable_name: str) -> str:
        """按数据库记录的变量名读取密钥，但不向业务层暴露 environ。"""
        if not variable_name:
            return ""
        name = variable_name.strip()
        # 拒绝读取应用自身的敏感变量，防止被配置为 api_key_env 后随外部请求外泄。
        if name.upper() in _PROTECTED_ENV_NAMES:
            return ""
        return os.environ.get(name, "").strip()

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


def _write_private_file(path: Path, content: str) -> None:
    """以仅所有者可读写权限写入密钥文件，避免本地其他用户读取（CWE-732）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        # Windows 等平台可能不支持 POSIX 权限位，忽略即可。
        pass
    path.write_text(content, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


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
    generated = secrets.token_urlsafe(48)
    _write_private_file(secret_file, generated)
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
    generated = secrets.token_urlsafe(48)
    _write_private_file(key_file, generated)
    return generated


def _initial_admin_password(app_env: str) -> str:
    """初始超管口令：环境变量优先；未配置时自动生成强随机密码并写入本地文件。"""
    explicit = _value("ADMIN_INITIAL_PASSWORD", "DATAFINDER_ADMIN_PASSWORD").strip()
    if explicit:
        if len(explicit) < 6:
            raise RuntimeError("ADMIN_INITIAL_PASSWORD 至少需要 6 个字符")
        return explicit
    if app_env == "production":
        raise RuntimeError("生产环境必须通过 ADMIN_INITIAL_PASSWORD 提供初始管理员口令")
    # 非生产环境：优先读取 DEV_ADMIN_PASSWORD 环境变量
    dev = _value("DEV_ADMIN_PASSWORD", "").strip()
    if dev:
        return dev
    # 无环境变量时，生成强随机密码并持久化到本地文件（类似 cookie_secret 的处理方式）
    pwd_file = BASE_DIR / "config" / "runtime_admin_password.txt"
    if pwd_file.exists():
        stored = pwd_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    generated = secrets.token_urlsafe(12)
    _write_private_file(pwd_file, generated)
    print(f"[DataFinder] 已自动生成初始管理员密码并保存到 {pwd_file}，请妥善保管。")
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
        initial_admin_password=_initial_admin_password(app_env),
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
