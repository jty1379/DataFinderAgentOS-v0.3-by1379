CREATE TABLE IF NOT EXISTS sensitive_words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'default',
    level INTEGER NOT NULL DEFAULT 1 CHECK (level IN (1,2,3,4)),
    description TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS opinion_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL DEFAULT 'chat' CHECK (source_type IN ('chat', 'collection', 'employee', 'news')),
    source_id INTEGER,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    content TEXT NOT NULL,
    matched_words TEXT NOT NULL DEFAULT '[]',
    risk_level TEXT NOT NULL DEFAULT 'low' CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    ai_analysis TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'resolved', 'false_positive')),
    handled_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    handle_note TEXT NOT NULL DEFAULT '',
    handled_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS opinion_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL REFERENCES opinion_alerts(id) ON DELETE CASCADE,
    analysis_type TEXT NOT NULL DEFAULT 'sentiment' CHECK (analysis_type IN ('sentiment', 'topic', 'risk')),
    result TEXT NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id INTEGER,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    user_name TEXT NOT NULL DEFAULT '',
    ip_address TEXT NOT NULL DEFAULT '',
    action_before TEXT NOT NULL DEFAULT '{}',
    action_after TEXT NOT NULL DEFAULT '{}',
    detail TEXT NOT NULL DEFAULT '',
    success INTEGER NOT NULL DEFAULT 1 CHECK (success IN (0,1)),
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_sensitive_words_word ON sensitive_words(word);
CREATE INDEX IF NOT EXISTS ix_opinion_alerts_status ON opinion_alerts(status,created_at DESC);
CREATE INDEX IF NOT EXISTS ix_opinion_alerts_risk ON opinion_alerts(risk_level,created_at DESC);
CREATE INDEX IF NOT EXISTS ix_opinion_alerts_user ON opinion_alerts(user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_logs_user ON audit_logs(user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_logs_action ON audit_logs(action_type,created_at DESC);