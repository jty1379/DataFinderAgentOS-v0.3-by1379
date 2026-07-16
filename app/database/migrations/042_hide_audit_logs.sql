-- v0.3 不再向业务用户展示审计日志模块；底层日志仍供服务内部故障排查。
DELETE FROM menus
WHERE feature_id IN (SELECT id FROM features WHERE code='audit_logs');

DELETE FROM role_features
WHERE feature_id IN (SELECT id FROM features WHERE code='audit_logs');

UPDATE features
SET enabled=0, updated_at=CURRENT_TIMESTAMP
WHERE code='audit_logs';
