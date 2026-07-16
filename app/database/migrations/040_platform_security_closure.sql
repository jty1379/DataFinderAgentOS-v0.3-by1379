ALTER TABLE user_conversations ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','archived'));
ALTER TABLE user_conversations ADD COLUMN archived_at TEXT;

ALTER TABLE user_messages ADD COLUMN risk_level TEXT NOT NULL DEFAULT 'low'
    CHECK (risk_level IN ('low','medium','high','critical'));
ALTER TABLE user_messages ADD COLUMN matched_words TEXT NOT NULL DEFAULT '[]';
ALTER TABLE user_messages ADD COLUMN latency_ms INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms >= 0);
ALTER TABLE user_messages ADD COLUMN token_count INTEGER NOT NULL DEFAULT 0 CHECK (token_count >= 0);

UPDATE user_messages
SET latency_ms = CASE WHEN json_valid(metadata)
    THEN MAX(0,COALESCE(json_extract(metadata,'$.usage.latency_ms'),0)) ELSE 0 END,
    token_count = CASE WHEN json_valid(metadata)
    THEN MAX(0,COALESCE(json_extract(metadata,'$.usage.total_tokens'),0)) ELSE 0 END;

ALTER TABLE opinion_alerts ADD COLUMN content_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE opinion_alerts ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}';

CREATE UNIQUE INDEX IF NOT EXISTS ux_opinion_alert_source_content
    ON opinion_alerts(source_type,source_id,content_hash) WHERE content_hash<>'';
CREATE INDEX IF NOT EXISTS ix_conversations_admin_filter
    ON user_conversations(status,model_id,employee_id,created_at DESC);
CREATE INDEX IF NOT EXISTS ix_messages_risk
    ON user_messages(risk_level,conversation_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_resource
    ON audit_logs(resource_type,resource_id,created_at DESC);
