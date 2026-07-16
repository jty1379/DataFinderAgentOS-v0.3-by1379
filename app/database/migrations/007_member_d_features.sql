CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS face_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    embedding TEXT NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0 CHECK (sample_count >= 3),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    liveness_method TEXT NOT NULL DEFAULT 'multi_frame_motion',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gesture_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    gesture TEXT NOT NULL CHECK (gesture IN ('victory', 'fist', 'open_palm')),
    action TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 1),
    triggered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS opinion_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL CHECK (source_type IN ('user_message', 'collection')),
    source_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    excerpt TEXT NOT NULL DEFAULT '',
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    sensitive_words TEXT NOT NULL DEFAULT '[]',
    ai_analysis TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'processing', 'resolved', 'false_positive')),
    handler_note TEXT NOT NULL DEFAULT '',
    handled_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_face_profiles_enabled ON face_profiles(enabled);
CREATE INDEX IF NOT EXISTS idx_gesture_events_user_time ON gesture_events(user_id, triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_opinion_alerts_status_risk ON opinion_alerts(status, risk_level, created_at DESC);

INSERT OR IGNORE INTO system_settings(key, value) VALUES ('face_login_enabled', '1');
UPDATE features SET route='/admin/screens/intelligence' WHERE code='intelligence_screen';
UPDATE features SET route='/admin/screens/opinion' WHERE code='opinion_screen';
