# API 契约（v0.3 冻结基线）

## 通用约定

- JSON 成功：`{"success":true,"data":{},"message":"ok","request_id":"..."}`。
- JSON 失败：`{"success":false,"error":{"code":"...","message":"...","request_id":"..."}}`。
- 兼容期响应仍可能同时含 `ok`、`message` 和原业务顶层字段，新增前端必须优先读取 `success/data/error`。
- 前端统一通过 `DataFinderApp.request()` 调用 JSON 接口，不得在业务脚本中直接使用 `fetch`。
- 分页对象固定为 `items/page/page_size/total`。
- 时间使用 ISO 8601；布尔值必须是 JSON Boolean；实体 ID 使用整数。
- 所有 POST 请求启用 XSRF；管理接口还必须通过角色和功能权限校验。

## 用户侧

| 方法 | 地址 | 输入 | 输出/说明 |
|---|---|---|---|
| POST | `/login` | Form: `username,password` | 登录成功跳转 `/index` |
| POST | `/register` | Form: `username,password,password_confirm` | 创建普通用户 |
| GET | `/api/conversations/{id}` | - | 会话及消息，限本人 |
| DELETE | `/api/conversations/{id}` | XSRF | 删除本人会话 |
| POST | `/api/chat` | JSON: `message,conversation_id?,model_id?,employee_id?` | 非流式回复 |
| POST | `/api/chat/stream` | 同上 | SSE，见 EVENT_SCHEMA |

消息对象固定字段：`id, conversation_id, role, content, content_type, metadata, risk_level, matched_words, latency_ms, token_count, created_at`。`role` 为 `user/assistant`；`content_type` 为 `text/card/json/error`。

## 管理侧

页面路由保持：`/admin/`、`/admin/users`、`/admin/roles`、`/admin/features`、`/admin/menus`、`/admin/lookout`、`/admin/sources`、`/admin/warehouse`、`/admin/models`、`/admin/agents`。

| 方法 | 地址 | 权限 | 说明 |
|---|---|---|---|
| POST | `/admin/lookout/collect` | `lookout_management` | 执行采集规则 |
| POST | `/admin/warehouse/import` | `data_management` | 将采集结果入仓 |
| POST | `/admin/warehouse/deep-collect` | `data_management` | 创建深采任务 |
| GET | `/admin/warehouse/deep-tasks/{id}` | `data_management` | 查询任务状态 |
| GET | `/admin/warehouse/deep-results/{id}` | `data_management` | 查询深采结果 |
| POST | `/admin/models/chat` | `model_engine` | 模型 SSE 对话 |
| POST | `/admin/agents/preview` | `digital_employees` | 数字员工预览 |
| GET/POST | `/admin/sessions` | `session_management` + 超级管理员 | 会话筛选、归档和批量删除 |
| GET | `/admin/messages?conversation_id={id}` | `session_management` + 超级管理员 | 完整消息、风险与调用指标 |
| GET | `/admin/sessions/{id}/export.pdf` | `session_management` + 超级管理员 | 导出指定会话 |
| GET | `/admin/audit/logs` | `audit_logs` | 按动作、用户、资源和日期检索审计日志 |

用户、角色、功能和菜单写操作仅超级管理员可执行；其他获权管理角色为只读。

## 卡片

卡片固定为 `{"type":"<card_type>","data":{},"created_at":"ISO8601"}`。类型：`text,kpi,table,line_chart,bar_chart,pie_chart,weather,music,news,image,video`。

前端由 `DataFinderCards.render()` 统一渲染，具体约束见 `FRONTEND_CONTRACT.md`。

## A/B/C 冻结服务接口（2026-07-16）

### 数据库问数

`QueryIntentService.query(question, user_id=None) -> dict`

固定返回 `intent, conclusion, kpis, charts, table, generated_at`。查询只调用白名单 Repository，不接收或执行用户 SQL。

### 数字员工

`await DigitalEmployeeService.execute(employee_id, text, user_id=None) -> dict`

运行时读取员工绑定接口及已启用 Skills；返回中允许包含 `skills_used` 与 `security`，不得包含完整系统提示词或密钥。

### 舆情安全

`OpinionSecurityService.analyze_and_record(source_type, source_id, content, user_id=None, metadata=None) -> dict`

固定返回 `source_type, source_id, risk_level, matched_words, ai_analysis, alert_id`。相同来源、来源 ID 与内容哈希保持幂等。

### 操作审计

`AuditLogService.log_action(action_type, resource_type, resource_id=None, user_id=None, user_name='', ip_address='', action_before=None, action_after=None, detail='', success=True, error_message='')`

审计失败只写错误日志，不回滚已经完成的业务事务；禁止把密码、Cookie、Token、API Key 或完整请求体写入详情。

### 采集任务

采集状态固定为 `pending/running/success/partial/failed/cancelled`。进度与日志来自数据库，前端不得用计时器伪造。

### 多模态任务

任务状态固定为 `pending/running/completed/failed`；真实资源由 OpenAI 兼容生图服务返回或落入本地受控资源目录。没有视频服务时必须落库为失败并明确“未配置/不可用”。
