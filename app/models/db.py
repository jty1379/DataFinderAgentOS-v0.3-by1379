"""SQLite 连接、增量迁移与权限基础数据初始化。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from config.settings import DATABASE_PATH


DEFAULT_FEATURES = (
    ("dashboard", "工作台", "/admin/", "layui-icon-console", "核心工作区", "系统运行概览与关键指标", 10, 1),
    ("user_management", "用户管理", "/admin/users", "layui-icon-user", "核心工作区", "集中管理普通用户与管理员账号", 20, 1),
    ("feature_management", "功能管理", "/admin/features", "layui-icon-component", "核心工作区", "维护系统功能及启用状态", 30, 1),
    ("menu_management", "菜单管理", "/admin/menus", "layui-icon-cols", "核心工作区", "配置、排序并预览管理端菜单", 40, 1),
    ("role_management", "角色管理", "/admin/roles", "layui-icon-auz", "核心工作区", "维护角色及其功能授权", 50, 1),
    ("lookout_management", "瞭望采集", "/admin/lookout", "layui-icon-chart-screen", "数据与智能", "按瞭源规则采集并预览公开数据", 60, 1),
    ("data_management", "数据仓库", "/admin/warehouse", "layui-icon-diamond", "数据与智能", "管理已入库的采集数据与深度采集状态", 70, 1),
    ("collection_management", "瞭源管理", "/admin/sources", "layui-icon-download-circle", "数据与智能", "维护公开数据源、请求头和采集规则", 80, 1),
    ("digital_employees", "数字员工", "/admin/agents", "layui-icon-username", "数据与智能", "配置模型型与接口型数字员工，并支持后台任务调度", 90, 1),
    ("model_engine", "模型引擎", "/admin/models", "layui-icon-engine", "数据与智能", "配置 OpenAI 兼容模型、默认服务和生成参数", 100, 1),
    ("intelligence_screen", "数智大屏", "/admin/modules/intelligence", "layui-icon-chart", "数据与智能", "呈现核心业务指标", 110, 1),
    ("opinion_screen", "舆情大屏", "/admin/modules/opinion", "layui-icon-fire", "数据与智能", "聚合热点事件与舆情趋势", 120, 1),
    ("user_portal", "用户侧门户", "/index", "layui-icon-dialogue", "用户侧", "用户登录、问数与数字员工入口", 130, 1),
)

V02_FEATURE_CODES = (
    "lookout_management",
    "data_management",
    "collection_management",
    "model_engine",
)

V03_FEATURE_CODES = V02_FEATURE_CODES + ("digital_employees",)

SAFE_BAIDU_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Chromium";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
}


def get_connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextmanager
def connection_scope():
    """保证连接在事务完成后关闭，避免 Windows 文件锁。"""
    connection = get_connection()
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _add_column_if_missing(connection, table: str, column: str, definition: str) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _seed_permissions(connection) -> None:
    connection.executemany(
        """
        INSERT OR IGNORE INTO roles
            (code, name, description, access_scope, enabled, is_system)
        VALUES (?, ?, ?, ?, 1, 1)
        """,
        (
            ("user", "普通用户", "只能登录用户侧并使用已授权能力", "user"),
            ("admin", "系统管理员", "只能登录管理侧并维护系统配置", "admin"),
        ),
    )
    connection.executemany(
        """
        INSERT OR IGNORE INTO features
            (code, name, route, icon, category, description, sort_order, enabled, is_system)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        DEFAULT_FEATURES,
    )

    # INSERT OR IGNORE 不会更新 v0.1 已存在的内置功能，因此显式同步
    # day6-2 的四个业务入口，并保留原 feature id 与角色授权关系。
    for feature in DEFAULT_FEATURES:
        code, name, route, icon, category, description, sort_order, is_system = feature
        if code in V03_FEATURE_CODES:
            connection.execute(
                """
                UPDATE features
                SET name = ?, route = ?, icon = ?, category = ?, description = ?,
                    sort_order = ?, is_system = ?, enabled = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE code = ?
                """,
                (name, route, icon, category, description, sort_order, is_system, code),
            )

    admin_role = connection.execute(
        "SELECT id FROM roles WHERE code = 'admin'"
    ).fetchone()
    user_role = connection.execute(
        "SELECT id FROM roles WHERE code = 'user'"
    ).fetchone()
    if admin_role:
        # 每次启动都补齐系统管理员的内置后台功能。这避免 v0.1
        # 数据库在新增 v0.2 功能后因已有其他授权而漏授权。
        connection.execute(
            """
            INSERT OR IGNORE INTO role_features (role_id, feature_id)
            SELECT ?, id FROM features
            WHERE route LIKE '/admin/%' AND is_system = 1
            """,
            (admin_role["id"],),
        )
    if user_role:
        connection.execute(
            """
            INSERT OR IGNORE INTO role_features (role_id, feature_id)
            SELECT ?, id FROM features WHERE code = 'user_portal'
            """,
            (user_role["id"],),
        )

    connection.execute(
        """
        INSERT OR IGNORE INTO menus
            (feature_id, title, icon, category, sort_order, enabled, is_system)
        SELECT id, name, icon, category, sort_order, 1, 1
        FROM features WHERE route LIKE '/admin/%'
        """
    )

    connection.execute(
        """
        UPDATE menus
        SET title = (SELECT name FROM features WHERE features.id = menus.feature_id),
            icon = (SELECT icon FROM features WHERE features.id = menus.feature_id),
            category = (SELECT category FROM features WHERE features.id = menus.feature_id),
            sort_order = (SELECT sort_order FROM features WHERE features.id = menus.feature_id),
            updated_at = CURRENT_TIMESTAMP
        WHERE feature_id IN (
            SELECT id FROM features
            WHERE code IN ('lookout_management', 'data_management',
                           'collection_management', 'model_engine',
                           'digital_employees')
        )
        """
    )


def _mark_legacy_superadmin(connection) -> None:
    """Promote the legacy seeded ``admin`` account without changing its password."""
    existing = connection.execute(
        "SELECT id FROM users WHERE is_superadmin = 1 LIMIT 1"
    ).fetchone()
    if existing:
        return
    admin_role = connection.execute(
        "SELECT id FROM roles WHERE code = 'admin'"
    ).fetchone()
    legacy_admin = connection.execute(
        "SELECT id FROM users WHERE username = 'admin'"
    ).fetchone()
    if admin_role and legacy_admin:
        connection.execute(
            """
            UPDATE users
            SET role = 'admin', role_id = ?, status = 'enabled',
                is_superadmin = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (admin_role["id"], legacy_admin["id"]),
        )


def _seed_public_sources(connection) -> None:
    """Seed a public Baidu News rule; never persist copied browser credentials."""
    connection.execute(
        """
        INSERT OR IGNORE INTO lookout_sources
            (code, name, base_url, description, default_headers, enabled)
        VALUES ('baidu_news', ?, ?, ?, ?, 1)
        """,
        (
            "百度新闻",
            "https://www.baidu.com/s",
            "公开新闻搜索演示源；不保存 Cookie 或登录凭据。",
            json.dumps(SAFE_BAIDU_HEADERS, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    connection.execute(
        """
        UPDATE lookout_sources SET code = 'baidu_news'
        WHERE name = '百度新闻' AND code = ''
        """
    )
    source = connection.execute(
        "SELECT id FROM lookout_sources WHERE name = '百度新闻'"
    ).fetchone()
    if source:
        connection.execute(
            """
            INSERT OR IGNORE INTO collection_rules
                (source_id, name, keyword_param, page_param, page_start, page_step,
                 page_size, fixed_params, request_headers, parser_type, parser_config,
                 enabled)
            VALUES (?, ?, 'word', 'pn', 0, 10, 12, ?, '{}', 'baidu_news', ?, 1)
            """,
            (
                source["id"],
                "百度新闻关键词采集",
                json.dumps(
                    {"rtt": "1", "bsst": "1", "cl": "2", "tn": "news", "rsv_dl": "ns_pc"},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                json.dumps({"result_limit": 12}, separators=(",", ":")),
            ),
        )


def init_db() -> None:
    """建表并兼容早期仅包含 users.role 的数据库。"""
    with connection_scope() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                access_scope TEXT NOT NULL CHECK (access_scope IN ('user', 'admin')),
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                is_system INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
                role_id INTEGER REFERENCES roles(id),
                status TEXT NOT NULL DEFAULT 'enabled' CHECK (status IN ('enabled', 'disabled')),
                is_superadmin INTEGER NOT NULL DEFAULT 0 CHECK (is_superadmin IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER REFERENCES features(id) ON DELETE RESTRICT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                route TEXT NOT NULL UNIQUE,
                icon TEXT NOT NULL DEFAULT 'layui-icon-app',
                category TEXT NOT NULL DEFAULT '自定义功能',
                description TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                sort_order INTEGER NOT NULL DEFAULT 100,
                is_system INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS role_features (
                role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                feature_id INTEGER NOT NULL REFERENCES features(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (role_id, feature_id)
            );

            CREATE TABLE IF NOT EXISTS menus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feature_id INTEGER NOT NULL UNIQUE REFERENCES features(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                icon TEXT NOT NULL DEFAULT 'layui-icon-app',
                category TEXT NOT NULL DEFAULT '自定义功能',
                sort_order INTEGER NOT NULL DEFAULT 100,
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                is_system INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL DEFAULT '',
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS lookout_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL UNIQUE,
                base_url TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                default_headers TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS collection_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES lookout_sources(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                keyword_param TEXT NOT NULL DEFAULT 'word',
                page_param TEXT NOT NULL DEFAULT 'pn',
                page_start INTEGER NOT NULL DEFAULT 0,
                page_step INTEGER NOT NULL DEFAULT 10 CHECK (page_step > 0),
                page_size INTEGER NOT NULL DEFAULT 12 CHECK (page_size BETWEEN 1 AND 100),
                fixed_params TEXT NOT NULL DEFAULT '{}',
                request_headers TEXT NOT NULL DEFAULT '{}',
                parser_type TEXT NOT NULL DEFAULT 'generic_links',
                parser_config TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (source_id, name)
            );

            CREATE TABLE IF NOT EXISTS collection_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id INTEGER REFERENCES collection_rules(id) ON DELETE SET NULL,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                keyword TEXT NOT NULL,
                page_number INTEGER NOT NULL DEFAULT 1 CHECK (page_number > 0),
                page_size INTEGER NOT NULL DEFAULT 12 CHECK (page_size BETWEEN 1 AND 100),
                request_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'success', 'failed')),
                result_count INTEGER NOT NULL DEFAULT 0 CHECK (result_count >= 0),
                error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS collection_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES collection_runs(id) ON DELETE CASCADE,
                rule_id INTEGER REFERENCES collection_rules(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                source_name TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                raw_data TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (run_id, url)
            );

            CREATE TABLE IF NOT EXISTS warehouse_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_result_id INTEGER REFERENCES collection_results(id) ON DELETE SET NULL,
                rule_id INTEGER REFERENCES collection_rules(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                summary TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                source_name TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                raw_data TEXT NOT NULL DEFAULT '{}',
                deep_collected INTEGER NOT NULL DEFAULT 0 CHECK (deep_collected IN (0, 1)),
                created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS model_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                model_name TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'OpenAI Compatible',
                model_type TEXT NOT NULL DEFAULT 'text'
                    CHECK (model_type IN ('text', 'image', 'audio', 'video',
                                          'multimodal', 'embedding')),
                base_url TEXT NOT NULL,
                api_key_env TEXT NOT NULL DEFAULT 'OPENAI_API_KEY',
                system_prompt TEXT NOT NULL DEFAULT '',
                temperature REAL NOT NULL DEFAULT 0.7 CHECK (temperature BETWEEN 0 AND 2),
                top_p REAL NOT NULL DEFAULT 1.0 CHECK (top_p BETWEEN 0 AND 1),
                max_tokens INTEGER NOT NULL DEFAULT 2048 CHECK (max_tokens BETWEEN 1 AND 131072),
                context_messages INTEGER NOT NULL DEFAULT 10 CHECK (context_messages BETWEEN 1 AND 100),
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
                created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS model_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id INTEGER NOT NULL REFERENCES model_configs(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
                completion_tokens INTEGER NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),
                total_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
                latency_ms INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
                success INTEGER NOT NULL DEFAULT 1 CHECK (success IN (0, 1)),
                error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS digital_employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL UNIQUE,
                mention TEXT NOT NULL UNIQUE,
                employee_type TEXT NOT NULL CHECK (employee_type IN ('llm', 'api')),
                description TEXT NOT NULL DEFAULT '',
                model_id INTEGER REFERENCES model_configs(id) ON DELETE SET NULL,
                use_default_model INTEGER NOT NULL DEFAULT 1 CHECK (use_default_model IN (0, 1)),
                system_prompt TEXT NOT NULL DEFAULT '',
                prompt_template TEXT NOT NULL DEFAULT '{{input}}',
                skills TEXT NOT NULL DEFAULT '[]',
                crawl4ai_enabled INTEGER NOT NULL DEFAULT 0 CHECK (crawl4ai_enabled IN (0, 1)),
                crawl4ai_config TEXT NOT NULL DEFAULT '{}',
                api_method TEXT NOT NULL DEFAULT 'GET' CHECK (api_method IN ('GET', 'POST')),
                api_url TEXT NOT NULL DEFAULT '',
                request_headers TEXT NOT NULL DEFAULT '{}',
                request_params TEXT NOT NULL DEFAULT '{}',
                response_mode TEXT NOT NULL DEFAULT 'json' CHECK (response_mode IN ('json', 'card')),
                timeout_seconds INTEGER NOT NULL DEFAULT 20 CHECK (timeout_seconds BETWEEN 3 AND 60),
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                is_system INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1)),
                created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS deep_collection_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                warehouse_item_id INTEGER NOT NULL REFERENCES warehouse_items(id) ON DELETE CASCADE,
                employee_id INTEGER REFERENCES digital_employees(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'success', 'failed')),
                progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
                current_step TEXT NOT NULL DEFAULT '等待调度',
                total_steps INTEGER NOT NULL DEFAULT 6 CHECK (total_steps > 0),
                is_update INTEGER NOT NULL DEFAULT 0 CHECK (is_update IN (0, 1)),
                started_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS deep_collection_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES deep_collection_tasks(id) ON DELETE CASCADE,
                level TEXT NOT NULL DEFAULT 'info' CHECK (level IN ('info', 'success', 'warning', 'error')),
                step TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS deep_collection_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL UNIQUE REFERENCES deep_collection_tasks(id) ON DELETE CASCADE,
                warehouse_item_id INTEGER NOT NULL REFERENCES warehouse_items(id) ON DELETE CASCADE,
                employee_id INTEGER REFERENCES digital_employees(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                excerpt TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL DEFAULT '新对话',
                model_id INTEGER REFERENCES model_configs(id) ON DELETE SET NULL,
                employee_id INTEGER REFERENCES digital_employees(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL REFERENCES user_conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                content_type TEXT NOT NULL DEFAULT 'text'
                    CHECK (content_type IN ('text', 'card', 'json', 'error')),
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        _add_column_if_missing(connection, "users", "role_id", "INTEGER REFERENCES roles(id)")
        _add_column_if_missing(connection, "users", "status", "TEXT NOT NULL DEFAULT 'enabled'")
        _add_column_if_missing(connection, "users", "updated_at", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(
            connection,
            "users",
            "is_superadmin",
            "INTEGER NOT NULL DEFAULT 0 CHECK (is_superadmin IN (0, 1))",
        )
        # day6-2 权限管理要求功能采用一级 + 二级结构。旧数据库中的功能
        # 自动保留为一级功能；parent_id 为空即根节点。
        _add_column_if_missing(
            connection,
            "features",
            "parent_id",
            "INTEGER REFERENCES features(id) ON DELETE RESTRICT",
        )
        _add_column_if_missing(connection, "lookout_sources", "code", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(
            connection,
            "model_configs",
            "provider",
            "TEXT NOT NULL DEFAULT 'OpenAI Compatible'",
        )
        _seed_permissions(connection)
        connection.execute(
            """
            UPDATE users
            SET role_id = (SELECT id FROM roles WHERE roles.code = users.role)
            WHERE role_id IS NULL
            """
        )
        connection.execute(
            "UPDATE users SET updated_at = created_at WHERE updated_at = ''"
        )
        _mark_legacy_superadmin(connection)
        connection.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_users_single_superadmin
                ON users(is_superadmin) WHERE is_superadmin = 1;
            CREATE INDEX IF NOT EXISTS ix_users_role_status ON users(role_id, status);
            CREATE INDEX IF NOT EXISTS ix_role_features_feature ON role_features(feature_id);
            CREATE INDEX IF NOT EXISTS ix_features_parent_sort
                ON features(parent_id, sort_order, id);
            CREATE INDEX IF NOT EXISTS ix_collection_rules_source_enabled
                ON collection_rules(source_id, enabled);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_lookout_sources_code
                ON lookout_sources(code) WHERE code <> '';
            CREATE INDEX IF NOT EXISTS ix_collection_runs_created
                ON collection_runs(created_at DESC);
            CREATE INDEX IF NOT EXISTS ix_collection_results_run
                ON collection_results(run_id, id);
            CREATE INDEX IF NOT EXISTS ix_warehouse_created
                ON warehouse_items(created_at DESC);
            CREATE INDEX IF NOT EXISTS ix_warehouse_deep
                ON warehouse_items(deep_collected, created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_model_single_default
                ON model_configs(is_default) WHERE is_default = 1;
            CREATE INDEX IF NOT EXISTS ix_models_type_enabled
                ON model_configs(model_type, enabled);
            CREATE INDEX IF NOT EXISTS ix_model_usage_model_created
                ON model_usage(model_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS ix_digital_employees_type_enabled
                ON digital_employees(employee_type, enabled, id DESC);
            CREATE INDEX IF NOT EXISTS ix_deep_tasks_item_created
                ON deep_collection_tasks(warehouse_item_id, id DESC);
            CREATE INDEX IF NOT EXISTS ix_deep_tasks_status_created
                ON deep_collection_tasks(status, id DESC);
            CREATE INDEX IF NOT EXISTS ix_deep_logs_task
                ON deep_collection_logs(task_id, id);
            CREATE INDEX IF NOT EXISTS ix_deep_results_item_created
                ON deep_collection_results(warehouse_item_id, id DESC);
            CREATE INDEX IF NOT EXISTS ix_user_conversations_user_updated
                ON user_conversations(user_id, updated_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS ix_user_messages_conversation
                ON user_messages(conversation_id, id);
            """
        )
        _seed_public_sources(connection)
        connection.execute(
            """
            INSERT OR IGNORE INTO schema_migrations (version, description)
            VALUES (2, 'day6-2 permissions, collection, warehouse and model engine')
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO schema_migrations (version, description)
            VALUES (3, 'two-level feature hierarchy and permission pagination')
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO digital_employees
                (code, name, mention, employee_type, description, use_default_model,
                 system_prompt, prompt_template, skills, crawl4ai_enabled,
                 crawl4ai_config, enabled, is_system)
            VALUES ('collection_specialist', '采集专员', '采集专员', 'llm', ?, 1,
                    ?, '{{input}}', ?, 1, ?, 1, 1)
            """,
            (
                "负责公开网页正文提取、字段整理与深度采集任务执行。",
                "你是数据采集专员，仅处理公开网页，输出可追溯的结构化采集结果。",
                json.dumps(["网页正文提取", "字段整理", "来源追溯"], ensure_ascii=False),
                json.dumps({"reader": "crawl4ai", "max_chars": 200000}, ensure_ascii=False),
            ),
        )
        connection.execute(
            """
            UPDATE digital_employees
            SET crawl4ai_enabled = 1,
                crawl4ai_config = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE code = 'collection_specialist'
            """,
            (json.dumps({"reader": "crawl4ai", "max_chars": 200000}, ensure_ascii=False),),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO digital_employees
                (code, name, mention, employee_type, description, use_default_model,
                 skills, api_method, api_url, request_headers, request_params,
                 response_mode, timeout_seconds, enabled, is_system)
            VALUES ('weather', '天气专员', '天气', 'api', ?, 1,
                    ?, 'GET', 'https://wttr.in/{{input_url}}', '{}', ?,
                    'card', 20, 1, 1)
            """,
            (
                "通过 wttr.in 公共接口查询城市当前天气与未来三日预报。",
                json.dumps(["实时天气", "三日预报", "城市气象"], ensure_ascii=False),
                json.dumps({"format": "j1", "lang": "zh"}, ensure_ascii=False),
            ),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO schema_migrations (version, description)
            VALUES (4, 'digital employees and persistent deep collection tasks')
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO schema_migrations (version, description)
            VALUES (5, 'crawl4ai deep collection, weather employee and user conversations')
            """
        )
        connection.commit()
