"""生产环境安全默认值。"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULTS = {
    "debug": False,
    "host": "127.0.0.1",
    "port": 10010,
    "database_path": BASE_DIR / "data" / "finderos.db",
}
