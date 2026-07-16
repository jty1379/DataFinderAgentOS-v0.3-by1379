CREATE TABLE IF NOT EXISTS tts_config (
    id INTEGER PRIMARY KEY DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    provider TEXT NOT NULL DEFAULT 'volcengine',
    default_voice TEXT NOT NULL DEFAULT 'zh_female',
    api_key_env TEXT NOT NULL DEFAULT '',
    api_secret_env TEXT NOT NULL DEFAULT '',
    base_url TEXT NOT NULL DEFAULT '',
    rate INTEGER NOT NULL DEFAULT 0,
    volume INTEGER NOT NULL DEFAULT 0,
    pitch INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(id)
);

CREATE TABLE IF NOT EXISTS tts_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text_length INTEGER NOT NULL DEFAULT 0,
    voice TEXT NOT NULL DEFAULT '',
    success INTEGER NOT NULL DEFAULT 1 CHECK (success IN (0, 1)),
    error_message TEXT NOT NULL DEFAULT '',
    latency_ms INTEGER NOT NULL DEFAULT 0,
    from_cache INTEGER NOT NULL DEFAULT 0 CHECK (from_cache IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tts_calls_date ON tts_calls(created_at);
CREATE INDEX IF NOT EXISTS idx_tts_calls_voice ON tts_calls(voice);
