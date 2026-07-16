CREATE TABLE IF NOT EXISTS api_interfaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    api_url TEXT NOT NULL,
    request_method TEXT NOT NULL DEFAULT 'GET' CHECK (request_method IN ('GET', 'POST')),
    request_headers TEXT NOT NULL DEFAULT '{}',
    request_params TEXT NOT NULL DEFAULT '{}',
    response_path TEXT NOT NULL DEFAULT '',
    timeout_seconds INTEGER NOT NULL DEFAULT 15 CHECK (timeout_seconds BETWEEN 3 AND 60),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count BETWEEN 0 AND 5),
    description TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS interface_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interface_id INTEGER NOT NULL REFERENCES api_interfaces(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    status_code INTEGER NOT NULL DEFAULT 0,
    success INTEGER NOT NULL DEFAULT 1 CHECK (success IN (0, 1)),
    error_message TEXT NOT NULL DEFAULT '',
    latency_ms INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_interface_calls_interface ON interface_calls(interface_id);
CREATE INDEX IF NOT EXISTS idx_interface_calls_created_at ON interface_calls(created_at);
