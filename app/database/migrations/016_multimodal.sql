CREATE TABLE IF NOT EXISTS multimodal_config (
    id INTEGER PRIMARY KEY,
    enabled INTEGER DEFAULT 1,
    provider TEXT DEFAULT 'volcengine',
    api_key_env TEXT DEFAULT '',
    api_secret_env TEXT DEFAULT '',
    base_url TEXT DEFAULT '',
    default_image_size TEXT DEFAULT '1024x1024',
    default_video_duration INTEGER DEFAULT 5,
    created_at REAL DEFAULT (strftime('%s', 'now')),
    updated_at REAL DEFAULT (strftime('%s', 'now'))
);

INSERT OR IGNORE INTO multimodal_config (id, enabled, provider, api_key_env, api_secret_env, base_url, default_image_size, default_video_duration) 
VALUES (1, 1, 'volcengine', '', '', '', '1024x1024', 5);

CREATE TABLE IF NOT EXISTS multimodal_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    task_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    status TEXT DEFAULT 'running',
    result TEXT DEFAULT '',
    created_at REAL DEFAULT (strftime('%s', 'now')),
    updated_at REAL DEFAULT (strftime('%s', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_multimodal_calls_task_type ON multimodal_calls(task_type);
CREATE INDEX IF NOT EXISTS idx_multimodal_calls_status ON multimodal_calls(status);
CREATE INDEX IF NOT EXISTS idx_multimodal_calls_created_at ON multimodal_calls(created_at);
