CREATE TABLE IF NOT EXISTS system_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setting_key TEXT NOT NULL UNIQUE,
    setting_value TEXT NOT NULL DEFAULT '',
    setting_type TEXT NOT NULL DEFAULT 'string' CHECK (setting_type IN ('string', 'integer', 'boolean', 'float', 'json')),
    description TEXT NOT NULL DEFAULT '',
    is_sensitive INTEGER NOT NULL DEFAULT 0 CHECK (is_sensitive IN (0,1)),
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_settings_key ON system_settings(setting_key);