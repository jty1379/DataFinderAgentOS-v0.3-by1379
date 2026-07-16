# 数据库结构基线

数据库为 SQLite，外键开启，WAL 模式。结构由 `app/database/migrations` 管理；`schema_migrations(version,name,applied_at,checksum)` 记录一次性迁移，兼容字段 `description` 暂时保留。

| 领域 | 表 | 关键关系/约束 |
|---|---|---|
| 认证 | `users` | username 唯一；role_id → roles；仅一个 is_superadmin=1 |
| RBAC | `roles` | code 唯一；access_scope=user/admin |
| RBAC | `features` | code、route 唯一；parent_id 自关联 |
| RBAC | `role_features` | role_id + feature_id 联合主键 |
| RBAC | `menus` | feature_id 唯一并级联删除 |
| 采集 | `lookout_sources` | code、name 唯一 |
| 采集 | `collection_rules` | source_id → lookout_sources；源内名称唯一 |
| 采集 | `collection_runs` | 规则、执行人、状态、请求地址 |
| 采集 | `collection_results` | run_id → runs；run 内 URL 唯一 |
| 仓库 | `warehouse_items` | URL 唯一；保留来源结果和规则引用 |
| 模型 | `model_configs` | name 唯一；仅一个默认模型 |
| 模型 | `model_usage` | model_id → model_configs |
| 员工 | `digital_employees` | code/name/mention 唯一；可引用模型 |
| 深采 | `deep_collection_tasks` | warehouse_item_id；pending/running/success/failed |
| 深采 | `deep_collection_logs` | task_id 级联删除 |
| 深采 | `deep_collection_results` | task_id 唯一；关联仓库与员工 |
| 对话 | `user_conversations` | user_id 级联删除；可引用模型和员工 |
| 对话 | `user_messages` | conversation_id 级联删除；role/content_type 受约束 |

## 变更规则

新表、字段和索引只能通过新的递增 SQL 迁移加入。迁移文件执行后不得修改；runner 会比较 SHA-256 校验和。种子数据使用唯一键和 `INSERT OR IGNORE`，允许重复启动。模型密钥只保存环境变量名，不保存真实 Key。
