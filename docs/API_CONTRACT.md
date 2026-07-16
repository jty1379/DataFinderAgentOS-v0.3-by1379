# API 契约（v0.3 冻结基线）

## 通用约定

- JSON 成功：`{"success":true,"data":{},"message":"ok","request_id":"..."}`。
- JSON 失败：`{"success":false,"error":{"code":"...","message":"...","request_id":"..."}}`。
- 兼容期响应仍可能同时含 `ok`、`message` 和原业务顶层字段，新增前端必须优先读取 `success/data/error`。
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

消息对象固定字段：`id, conversation_id, role, content, content_type, metadata, created_at`。`role` 为 `user/assistant`；`content_type` 为 `text/card/json/error`。

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

用户、角色、功能和菜单写操作仅超级管理员可执行；其他获权管理角色为只读。

## 卡片

卡片固定为 `{"type":"<card_type>","data":{},"created_at":"ISO8601"}`。类型：`text,kpi,table,line_chart,bar_chart,pie_chart,weather,music,news,image,video`。
