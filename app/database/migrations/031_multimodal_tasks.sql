ALTER TABLE multimodal_config ADD COLUMN image_model TEXT NOT NULL DEFAULT '';
ALTER TABLE multimodal_config ADD COLUMN video_enabled INTEGER NOT NULL DEFAULT 0 CHECK (video_enabled IN (0,1));

UPDATE multimodal_config
SET enabled=0, provider='openai_compatible'
WHERE TRIM(base_url)='';

CREATE TABLE IF NOT EXISTS multimodal_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    task_type TEXT NOT NULL CHECK (task_type IN ('image','video')),
    provider TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL,
    parameters TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','running','completed','failed')),
    provider_task_id TEXT NOT NULL DEFAULT '',
    resource_url TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '{}',
    error_message TEXT NOT NULL DEFAULT '',
    latency_ms INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

INSERT OR IGNORE INTO multimodal_tasks
    (task_id,task_type,prompt,status,result,error_message,created_at,updated_at,completed_at)
SELECT task_id,
       CASE WHEN task_type='video' THEN 'video' ELSE 'image' END,
       prompt,
       CASE WHEN status IN ('pending','running','completed','failed') THEN status ELSE 'failed' END,
       CASE WHEN status='completed' AND json_valid(result) THEN result ELSE '{}' END,
       CASE WHEN status='failed' THEN substr(result,1,500) ELSE '' END,
       datetime(created_at,'unixepoch'),datetime(updated_at,'unixepoch'),
       CASE WHEN status IN ('completed','failed') THEN datetime(updated_at,'unixepoch') END
FROM multimodal_calls;

CREATE INDEX IF NOT EXISTS ix_multimodal_tasks_type ON multimodal_tasks(task_type,created_at DESC);
CREATE INDEX IF NOT EXISTS ix_multimodal_tasks_status ON multimodal_tasks(status,created_at DESC);
CREATE INDEX IF NOT EXISTS ix_multimodal_tasks_user ON multimodal_tasks(user_id,created_at DESC);
