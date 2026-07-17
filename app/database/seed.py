"""可重复执行的系统角色、权限、采集源和数字员工种子数据。"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3

from config.settings import SETTINGS

DEFAULT_FEATURES = (
    ("dashboard", "控制台", "/admin/", "layui-icon-console", "控制台", "系统运行概览与关键指标", 10, 1),
    ("user_management", "用户管理", "/admin/users", "layui-icon-user", "权限与系统", "集中管理普通用户与管理员账号", 20, 1),
    ("feature_management", "功能管理", "/admin/features", "layui-icon-component", "权限与系统", "维护可授权业务能力、路由及启停状态", 30, 1),
    ("role_management", "权限管理", "/admin/roles", "layui-icon-auz", "权限与系统", "维护角色、功能授权与管理侧访问范围", 40, 1),
    ("menu_management", "菜单管理", "/admin/menus", "layui-icon-cols", "权限与系统", "将功能映射为导航并配置分组、排序与显隐", 50, 1),
    ("system_settings", "系统设置", "/admin/settings", "layui-icon-set", "权限与系统", "配置系统全局参数和运行开关", 60, 1),
    ("lookout_management", "瞭望采集", "/admin/lookout", "layui-icon-chart-screen", "瞭望与数据", "执行单条、批量与深度采集任务", 70, 1),
    ("collection_management", "瞭源管理", "/admin/sources", "layui-icon-download-circle", "瞭望与数据", "维护真实数据源、请求参数和采集规则", 80, 1),
    ("data_management", "数据仓库", "/admin/warehouse", "layui-icon-diamond", "瞭望与数据", "管理已入库的采集数据与深度采集状态", 90, 1),
    ("model_engine", "模型引擎", "/admin/models", "layui-icon-engine", "模型与问数", "配置文本、图像、音频和视频模型及默认调用策略", 100, 1),
    ("interface_management", "接口管理", "/admin/interfaces", "layui-icon-link", "模型与问数", "配置外部 API 接口、测试和查看调用日志", 110, 1),
    ("digital_employees", "数字员工", "/admin/agents", "layui-icon-username", "模型与问数", "配置模型型与接口型数字员工，并支持后台任务调度", 120, 1),
    ("skill_management", "技能管理", "/admin/skills", "layui-icon-star", "模型与问数", "管理技能配置和绑定到数字员工", 130, 1),
    ("session_management", "会话与对话管理", "/admin/sessions", "layui-icon-dialogue", "模型与问数", "管理用户会话、对话消息链与 PDF 导出", 140, 1),
    ("intelligence_screen", "数智大屏", "/admin/screens/intelligence", "layui-icon-chart", "数智监管", "呈现真实业务指标、趋势与热点", 150, 1),
    ("opinion_screen", "舆情大屏", "/admin/screens/opinion", "layui-icon-fire", "数智监管", "聚合风险分布、敏感词、预警趋势和处置入口", 160, 1),
    ("opinion_management", "舆情预警", "/admin/opinion/alerts", "layui-icon-fire", "数智监管", "舆情大屏的预警与敏感词二级管理能力", 180, 1),
    ("tts_config", "语音合成", "/admin/tts", "layui-icon-voice", "模型与问数", "模型引擎的语音合成二级配置能力", 190, 1),
    ("multimodal_config", "多模态服务", "/admin/multimodal", "layui-icon-picture", "模型与问数", "模型引擎的生图、生视频二级配置能力", 200, 1),
    ("user_portal", "用户侧门户", "/index", "layui-icon-dialogue", "用户侧", "用户登录、问数与数字员工入口", 130, 1),
)

# 任务书要求的管理端一级能力。其余系统功能保留路由和权限，但只从父模块内部进入。
PRIMARY_ADMIN_MENU_CODES = (
    "dashboard", "user_management", "feature_management", "role_management",
    "menu_management", "system_settings", "lookout_management",
    "collection_management", "data_management", "model_engine",
    "interface_management", "digital_employees", "skill_management",
    "session_management", "intelligence_screen", "opinion_screen",
)

SAFE_BAIDU_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
}


def _seed_permissions(connection: sqlite3.Connection) -> None:
    connection.executemany(
        "INSERT OR IGNORE INTO roles(code,name,description,access_scope,enabled,is_system) VALUES (?,?,?,?,1,1)",
        (("user", "普通用户", "只能登录用户侧并使用已授权能力", "user"), ("admin", "系统管理员", "只能登录管理侧并维护系统配置", "admin")),
    )
    connection.executemany(
        """INSERT OR IGNORE INTO features
        (code,name,route,icon,category,description,sort_order,enabled,is_system)
        VALUES (?,?,?,?,?,?,?,1,?)""",
        DEFAULT_FEATURES,
    )
    for code, name, route, icon, category, description, sort_order, is_system in DEFAULT_FEATURES:
        connection.execute(
            """UPDATE features SET name=?,route=?,icon=?,category=?,description=?,sort_order=?,is_system=?,updated_at=CURRENT_TIMESTAMP
            WHERE code=?""",
            (name, route, icon, category, description, sort_order, is_system, code),
        )
    admin_role = connection.execute("SELECT id FROM roles WHERE code='admin'").fetchone()
    user_role = connection.execute("SELECT id FROM roles WHERE code='user'").fetchone()
    if admin_role:
        connection.execute("INSERT OR IGNORE INTO role_features(role_id,feature_id) SELECT ?,id FROM features WHERE route LIKE '/admin/%' AND is_system=1 AND enabled=1", (admin_role["id"],))
    if user_role:
        connection.execute("INSERT OR IGNORE INTO role_features(role_id,feature_id) SELECT ?,id FROM features WHERE code='user_portal'", (user_role["id"],))
    placeholders = ",".join("?" for _ in PRIMARY_ADMIN_MENU_CODES)
    connection.execute(
        f"""DELETE FROM menus WHERE is_system=1 AND feature_id IN
        (SELECT id FROM features WHERE code NOT IN ({placeholders}))""",
        PRIMARY_ADMIN_MENU_CODES,
    )
    connection.execute(
        f"""INSERT OR IGNORE INTO menus(feature_id,title,icon,category,sort_order,enabled,is_system)
        SELECT id,name,icon,category,sort_order,1,1 FROM features WHERE code IN ({placeholders})""",
        PRIMARY_ADMIN_MENU_CODES,
    )
    connection.execute("""UPDATE menus SET title=(SELECT name FROM features WHERE id=menus.feature_id),
        icon=(SELECT icon FROM features WHERE id=menus.feature_id), category=(SELECT category FROM features WHERE id=menus.feature_id),
        sort_order=(SELECT sort_order FROM features WHERE id=menus.feature_id), updated_at=CURRENT_TIMESTAMP
        WHERE is_system=1 AND feature_id IN (SELECT id FROM features WHERE route LIKE '/admin/%')""")


def _seed_admin(connection: sqlite3.Connection) -> None:
    """只在不存在 admin 时创建课堂演示管理员，不覆盖已有密码。"""
    if connection.execute("SELECT 1 FROM users WHERE username='admin' OR is_superadmin=1 LIMIT 1").fetchone():
        return
    role = connection.execute("SELECT id FROM roles WHERE code='admin'").fetchone()
    if not role:
        return
    salt = secrets.token_bytes(16)
    # 初始口令收口到 SETTINGS（环境变量优先，生产强制提供），不在代码中硬编码明文。
    password = SETTINGS.initial_admin_password.encode("utf-8")
    password_hash = hashlib.pbkdf2_hmac("sha256", password, salt, 100_000).hex()
    connection.execute(
        """INSERT INTO users(username,password_hash,salt,role,role_id,status,is_superadmin)
        VALUES ('admin',?,?, 'admin',?,'enabled',1)""",
        (password_hash, salt.hex(), role["id"]),
    )


def _upgrade_legacy_users(connection: sqlite3.Connection) -> None:
    connection.execute("UPDATE users SET role_id=(SELECT id FROM roles WHERE roles.code=users.role) WHERE role_id IS NULL")
    connection.execute("UPDATE users SET updated_at=created_at WHERE updated_at='' OR updated_at IS NULL")
    if connection.execute("SELECT 1 FROM users WHERE is_superadmin=1 LIMIT 1").fetchone():
        return
    admin_role = connection.execute("SELECT id FROM roles WHERE code='admin'").fetchone()
    legacy = connection.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if admin_role and legacy:
        connection.execute("UPDATE users SET role='admin',role_id=?,status='enabled',is_superadmin=1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (admin_role["id"], legacy["id"]))


def _seed_source(connection: sqlite3.Connection) -> None:
    connection.execute(
        """INSERT OR IGNORE INTO lookout_sources(code,name,base_url,description,default_headers,enabled)
        VALUES ('baidu_news','百度新闻','https://www.baidu.com/s','公开新闻搜索演示源；不保存 Cookie 或登录凭据。',?,1)""",
        (json.dumps(SAFE_BAIDU_HEADERS, ensure_ascii=False, separators=(",", ":")),),
    )
    connection.execute("UPDATE lookout_sources SET code='baidu_news' WHERE name='百度新闻' AND code='' ")
    source = connection.execute("SELECT id FROM lookout_sources WHERE name='百度新闻'").fetchone()
    if source:
        connection.execute(
            """INSERT OR IGNORE INTO collection_rules
            (source_id,name,keyword_param,page_param,page_start,page_step,page_size,fixed_params,request_headers,parser_type,parser_config,enabled)
            VALUES (?,'百度新闻关键词采集','word','pn',0,10,12,?,'{}','baidu_news',?,1)""",
            (source["id"], json.dumps({"rtt": "1", "bsst": "1", "cl": "2", "tn": "news", "rsv_dl": "ns_pc"}, separators=(",", ":")), '{"result_limit":12}'),
        )

    # Source 2: 四川大学新闻网 (SCU News)
    connection.execute(
        """INSERT OR IGNORE INTO lookout_sources(code,name,base_url,description,default_headers,enabled)
        VALUES ('scu_news','四川大学新闻网','https://news.scu.edu.cn/','四川大学官方新闻网站；校园动态与学术资讯。',?,1)""",
        (json.dumps(SAFE_BAIDU_HEADERS, ensure_ascii=False, separators=(",", ":")),),
    )
    scu_source = connection.execute("SELECT id FROM lookout_sources WHERE code='scu_news'").fetchone()
    if scu_source:
        connection.execute(
            """INSERT OR IGNORE INTO collection_rules
            (source_id,name,keyword_param,page_param,page_start,page_step,page_size,fixed_params,request_headers,parser_type,parser_config,enabled)
            VALUES (?,'四川大学新闻采集','word','page',1,1,20,'{}','{}','generic_links',?,1)""",
            (scu_source["id"], '{"result_limit":20}'),
        )

    # 旧版 36 氪搜索长期返回 404；原位升级为可解析的 Bing 新闻。
    legacy_source = connection.execute(
        "SELECT id FROM lookout_sources WHERE code='kr36_trending' OR name='36氪热点' LIMIT 1"
    ).fetchone()
    bing_source = connection.execute(
        "SELECT id FROM lookout_sources WHERE code='bing_news' LIMIT 1"
    ).fetchone()
    if legacy_source and not bing_source:
        connection.execute(
            """UPDATE lookout_sources SET code='bing_news',name='Bing 新闻',
               base_url='https://www.bing.com/news/search',
               description='聚合公开新闻搜索结果。',updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (legacy_source["id"],),
        )
        connection.execute(
            """UPDATE collection_rules SET name='Bing 新闻关键词采集',keyword_param='q',
               page_param='first',page_start=1,page_step=10,page_size=12,
               fixed_params='{}',parser_type='bing_news',
               parser_config='{"result_limit":12}',updated_at=CURRENT_TIMESTAMP
               WHERE source_id=?""",
            (legacy_source["id"],),
        )
    elif legacy_source and bing_source and legacy_source["id"] != bing_source["id"]:
        connection.execute("DELETE FROM lookout_sources WHERE id=?", (legacy_source["id"],))

    connection.execute(
        """INSERT OR IGNORE INTO lookout_sources(code,name,base_url,description,default_headers,enabled)
        VALUES ('bing_news','Bing 新闻','https://www.bing.com/news/search','聚合公开新闻搜索结果。',?,1)""",
        (json.dumps(SAFE_BAIDU_HEADERS, ensure_ascii=False, separators=(",", ":")),),
    )
    bing_source = connection.execute("SELECT id FROM lookout_sources WHERE code='bing_news'").fetchone()
    if bing_source:
        connection.execute(
            """UPDATE collection_rules SET parser_type='bing_news',
               updated_at=CURRENT_TIMESTAMP WHERE source_id=?""",
            (bing_source["id"],),
        )
        connection.execute(
            """INSERT OR IGNORE INTO collection_rules
            (source_id,name,keyword_param,page_param,page_start,page_step,page_size,fixed_params,request_headers,parser_type,parser_config,enabled)
            VALUES (?,'Bing 新闻关键词采集','q','first',1,10,12,'{}','{}','bing_news',?,1)""",
            (bing_source["id"], '{"result_limit":12}'),
        )

    # Source 4: 中国新闻网搜索（页面内嵌结构化结果，包含可信发布时间）。
    connection.execute(
        """INSERT OR IGNORE INTO lookout_sources(code,name,base_url,description,default_headers,enabled)
        VALUES ('chinanews','中国新闻网','https://sou.chinanews.com.cn/search.do','中国新闻网公开新闻检索。',?,1)""",
        (json.dumps(SAFE_BAIDU_HEADERS, ensure_ascii=False, separators=(",", ":")),),
    )
    chinanews_source = connection.execute(
        "SELECT id FROM lookout_sources WHERE code='chinanews'"
    ).fetchone()
    if chinanews_source:
        connection.execute(
            """INSERT OR IGNORE INTO collection_rules
            (source_id,name,keyword_param,page_param,page_start,page_step,page_size,fixed_params,request_headers,parser_type,parser_config,enabled)
            VALUES (?,'中国新闻网关键词采集','q','start',0,10,10,?,'{}','chinanews',?,1)""",
            (
                chinanews_source["id"],
                json.dumps({"ps": "10"}, separators=(",", ":")),
                '{"result_limit":10}',
            ),
        )


def _seed_employees(connection: sqlite3.Connection) -> None:
    legacy_music = connection.execute(
        "SELECT id FROM digital_employees WHERE code='music_assistant' LIMIT 1"
    ).fetchone()
    current_music = connection.execute(
        "SELECT id FROM digital_employees WHERE code='music' LIMIT 1"
    ).fetchone()
    if legacy_music and not current_music:
        connection.execute(
            "UPDATE digital_employees SET code='music' WHERE id=?",
            (legacy_music["id"],),
        )
    legacy_news = connection.execute(
        "SELECT id FROM digital_employees WHERE code='news_assistant' LIMIT 1"
    ).fetchone()
    current_news = connection.execute(
        "SELECT id FROM digital_employees WHERE code='news' LIMIT 1"
    ).fetchone()
    if legacy_news and not current_news:
        connection.execute(
            "UPDATE digital_employees SET code='news' WHERE id=?",
            (legacy_news["id"],),
        )
    connection.execute(
        """INSERT OR IGNORE INTO digital_employees
        (code,name,mention,employee_type,description,use_default_model,system_prompt,prompt_template,skills,crawl4ai_enabled,crawl4ai_config,enabled,is_system)
        VALUES ('collection_specialist','采集专员','采集专员','llm',?,1,?,'{{input}}',?,1,?,1,1)""",
        ("负责公开网页正文提取、字段整理与深度采集任务执行。", "你是数据采集专员，仅处理公开网页，输出可追溯的结构化采集结果。", json.dumps(["网页正文提取", "字段整理", "来源追溯"], ensure_ascii=False), '{"reader":"crawl4ai","max_chars":200000}'),
    )
    connection.execute(
        """UPDATE digital_employees SET crawl4ai_enabled=1,
        crawl4ai_config='{"reader":"crawl4ai","max_chars":200000}', updated_at=CURRENT_TIMESTAMP
        WHERE code='collection_specialist'"""
    )
    connection.execute(
        """INSERT OR IGNORE INTO digital_employees
        (code,name,mention,employee_type,description,use_default_model,skills,api_method,api_url,request_headers,request_params,response_mode,timeout_seconds,enabled,is_system)
        VALUES ('weather','天气专员','天气','api',?,1,?,'GET','https://wttr.in/{{input_url}}','{}',?,'card',20,1,1)""",
        ("通过 wttr.in 公共接口查询城市当前天气与未来三日预报。", json.dumps(["实时天气", "三日预报", "城市气象"], ensure_ascii=False), '{"format":"j1","lang":"zh"}'),
    )
    connection.execute(
        """INSERT OR IGNORE INTO digital_employees
        (code,name,mention,employee_type,description,use_default_model,system_prompt,prompt_template,skills,enabled,is_system)
        VALUES ('chuan','川哥','川哥','llm',?,1,?,?,?,1,1)""",
        ("川大校园问答助手，解答关于四川大学的各类问题。",
         "你是川哥，四川大学的校园助手。你熟悉川大的历史、文化、校区、专业、生活等方方面面。请用友好、专业的语气回答用户的问题，如果不确定请如实说明。",
         "请回答关于川大的问题：{{input}}",
         json.dumps(["校园问答", "川大信息", "生活指南"], ensure_ascii=False)),
    )
    connection.execute(
        """INSERT OR IGNORE INTO digital_employees
        (code,name,mention,employee_type,description,use_default_model,system_prompt,prompt_template,skills,enabled,is_system)
        VALUES ('copywriter','文案写作助手','文案助手','llm',?,1,?,?,?,1,1)""",
        ("专业的文案创作助手，帮助撰写各类宣传文案。",
         "你是专业的文案写作助手。你擅长撰写活动宣传、产品推广、品牌故事等各类文案。请根据用户需求创作高质量、有吸引力的文案内容。",
         "请帮我写一段文案：{{input}}",
         json.dumps(["文案创作", "活动策划", "品牌宣传"], ensure_ascii=False)),
    )
    connection.execute(
        """INSERT OR IGNORE INTO digital_employees
        (code,name,mention,employee_type,description,use_default_model,skills,api_method,api_url,request_headers,request_params,response_mode,timeout_seconds,enabled,is_system)
        VALUES ('music','音乐播放器','音乐','api',?,1,?,'GET','https://itunes.apple.com/search','{}',?,'card',20,1,1)""",
        ("搜索歌曲并在网站内直接播放公开试听片段。", json.dumps(["站内播放", "歌曲搜索", "试听控制"], ensure_ascii=False), '{"term":"{{input}}","media":"music","entity":"song","limit":10}'),
    )
    connection.execute(
        """UPDATE digital_employees SET name='音乐播放器',employee_type='api',description='搜索歌曲并在网站内直接播放公开试听片段。',
        skills=?,api_method='GET',api_url='https://itunes.apple.com/search',request_headers='{}',
        request_params='{"term":"{{input}}","media":"music","entity":"song","limit":10}',response_mode='card',
        system_prompt='',prompt_template='{{input}}',timeout_seconds=20,enabled=1,updated_at=CURRENT_TIMESTAMP
        WHERE code='music'""",
        (json.dumps(["站内播放", "歌曲搜索", "试听控制"], ensure_ascii=False),),
    )
    connection.execute(
        """INSERT OR IGNORE INTO digital_employees
        (code,name,mention,employee_type,description,use_default_model,system_prompt,prompt_template,skills,enabled,is_system)
        VALUES ('news','新闻专员','新闻','llm',?,1,'','{{input}}',?,1,1)""",
        ("实时新闻检索专员：按主题从已启用的公开新闻源检索最新新闻，并附可追溯来源链接。",
         json.dumps(["实时新闻检索", "多源聚合", "来源可追溯"], ensure_ascii=False)),
    )
    connection.execute(
        """UPDATE digital_employees SET
            description='实时新闻检索专员：按主题从已启用的公开新闻源检索最新新闻，并附可追溯来源链接。',
            system_prompt='',prompt_template='{{input}}',skills=?,updated_at=CURRENT_TIMESTAMP
        WHERE code='news'""",
        (json.dumps(["实时新闻检索", "多源聚合", "来源可追溯"], ensure_ascii=False),),
    )
    connection.execute(
        """INSERT OR IGNORE INTO digital_employees
        (code,name,mention,employee_type,description,use_default_model,skills,api_method,api_url,request_headers,request_params,response_mode,timeout_seconds,enabled,is_system)
        VALUES ('analyst','数据分析师','分析师','api',?,1,?,'GET','http://localhost:10010/api/warehouse/stats','{}',?,'card',20,1,1)""",
        ("分析数据仓库的统计信息，提供数据趋势分析。", json.dumps(["数据分析", "趋势分析", "统计报告"], ensure_ascii=False), '{"period":"week"}'),
    )


def _seed_employee_runtime_bindings(connection: sqlite3.Connection) -> None:
    """Upgrade built-in employees to managed interfaces and an executable query Skill."""
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(digital_employees)")}
    if "interface_id" not in columns:
        return
    for code in ("weather", "music"):
        employee = connection.execute(
            "SELECT * FROM digital_employees WHERE code=?", (code,)
        ).fetchone()
        if not employee:
            continue
        interface_code = f"employee_{code}"
        connection.execute(
            """INSERT OR IGNORE INTO api_interfaces
               (code,name,api_url,request_method,request_headers,request_params,
                response_path,timeout_seconds,retry_count,description,enabled)
               VALUES (?,?,?,?,?,?,?, ?,1,?,1)""",
            (
                interface_code,
                f"{employee['name']}托管接口",
                employee["api_url"],
                employee["api_method"],
                employee["request_headers"],
                employee["request_params"],
                "",
                employee["timeout_seconds"],
                f"由数字员工 {employee['name']} 使用的公开接口。",
            ),
        )
        connection.execute(
            """UPDATE digital_employees
               SET interface_id=(SELECT id FROM api_interfaces WHERE code=?),
                   updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND interface_id IS NULL""",
            (interface_code, employee["id"]),
        )
        connection.execute(
            """UPDATE api_interfaces SET name=?,api_url=?,request_method=?,request_headers=?,request_params=?,
               timeout_seconds=?,description=?,updated_at=CURRENT_TIMESTAMP WHERE code=?""",
            (
                f"{employee['name']}托管接口", employee["api_url"], employee["api_method"],
                employee["request_headers"], employee["request_params"], employee["timeout_seconds"],
                f"由数字员工 {employee['name']} 使用的公开接口。", interface_code,
            ),
        )

    connection.execute(
        """INSERT OR IGNORE INTO skills
           (code,name,description,system_prompt,trigger_condition,tools,triggers,enabled)
           VALUES ('database_query','数据库问数','读取仓库的白名单聚合统计，返回结论、KPI、图表和表格。',
                   '仅根据系统只读统计回答，不生成或执行用户 SQL。','绑定后直接执行问数工具',
                   '{"query_intent":{"service":"QueryIntentService.query"}}',
                   '{"always":true}',1)"""
    )
    connection.execute(
        """INSERT OR IGNORE INTO employee_skills(employee_id,skill_id)
           SELECT d.id,s.id FROM digital_employees d CROSS JOIN skills s
           WHERE d.code='analyst' AND s.code='database_query'"""
    )


def seed_database(connection: sqlite3.Connection) -> None:
    """幂等写入系统运行所需的最小初始数据。"""
    _seed_permissions(connection)
    _seed_admin(connection)
    _upgrade_legacy_users(connection)
    _seed_source(connection)
    _seed_employees(connection)
    _seed_employee_runtime_bindings(connection)
    _seed_settings(connection)
    _seed_opinion(connection)
    # 2—5 是早期课堂版已并入基线表结构的历史版本；7 以后均由正式迁移器记录，
    # 不能在种子阶段抢占版本号，否则成员分支的新迁移会被静默跳过。
    for version, description in ((2, "permissions and collection"), (3, "feature hierarchy"), (4, "digital employees"), (5, "conversations")):
        connection.execute("INSERT OR IGNORE INTO schema_migrations(version,name,description,checksum) VALUES (?,?,?,'legacy')", (version, f"legacy_{version}", description))


def _seed_settings(connection) -> None:
    from app.models.system_settings import SystemSettingsRepository
    SystemSettingsRepository.seed_defaults(connection)


def _seed_opinion(connection) -> None:
    from app.models.opinion import SensitiveWordRepository
    SensitiveWordRepository.seed_defaults(connection)
