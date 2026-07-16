-- 旧任务保留业务可理解的失败原因，不再直接暴露采集器内部诊断串。
UPDATE deep_collection_tasks
SET error_message='正文补全失败：该聚合页启用了内容保护，请换用新闻的原始媒体链接后重试。'
WHERE status='failed'
  AND (error_message LIKE '%anti-bot protection%'
       OR error_message LIKE '%minimal_text%'
       OR error_message LIKE '%script_heavy_shell%');

UPDATE deep_collection_logs
SET message='正文补全失败：该聚合页启用了内容保护，请换用新闻的原始媒体链接后重试。'
WHERE level='error'
  AND (message LIKE '%anti-bot protection%'
       OR message LIKE '%minimal_text%'
       OR message LIKE '%script_heavy_shell%');
