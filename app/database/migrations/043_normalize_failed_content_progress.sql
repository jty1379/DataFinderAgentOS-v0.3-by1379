-- 旧版失败任务曾被错误标记为 100%；回落到“获取公开原文”步骤的真实进度。
UPDATE deep_collection_tasks
SET progress=45
WHERE status='failed' AND progress>=100;
