"""测试环境默认值；测试夹具应进一步替换为独立临时数据库。"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULTS = {
    "debug": False,
    "host": "127.0.0.1",
    "port": 10011,
    "database_path": BASE_DIR / "data" / "testing.db",
}
