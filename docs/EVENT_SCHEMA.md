# SSE 事件契约

SSE 只允许六种事件：`meta`、`delta`、`card`、`audio`、`error`、`done`。每条消息以空行结束，`data` 为 UTF-8 JSON。

## 用户问数流

- `meta`：`{"status":"正在识别意图并查询数据","request_id":"..."}`。
- `delta`：`{"text":"分段文本"}`。
- `card`：完整 assistant 消息对象，`content_type` 为 `card`。
- `done`：`{"ok":true,"usage":{...},"conversation":{...}}`。
- `error`：`{"message":"可展示错误","conversation_id":1}`。

错误事件后服务端关闭连接。客户端必须保留已接收的 `delta`，并允许用户重试。

## 模型测试流

- `meta`：连接状态与 `request_id`。
- `delta`：`{"delta":"文本片段"}`。
- `done`：`{"ok":true,"status":"已完成","usage":{...}}`。
- `error`：`{"error":"可展示错误"}`。

不得新增临时事件名；需要扩展元信息时增加相应事件 `data` 字段并先更新本文档。
