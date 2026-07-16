# 前端公共契约

成员 D 维护以下三个公共模块，所有用户侧和管理侧异步页面必须复用，禁止再次直接编写 `fetch` 或 SSE 分块解析器。

## 请求层 `DataFinderApp`

文件：`app/static/js/app-core.js`

- `request(url, options)`：统一 JSON 请求、XSRF、超时、标准/兼容响应判断。
- `fetchResponse(url, options)`：仅供 SSE 等需要原始 Response 的公共基础模块调用。
- `announce(message, level)`：统一 Layui Layer 与无 Layui 时的 Toast。
- `errorMessage(error, fallback)`：展示安全错误；存在 request_id 时自动附带请求编号。
- `setBusy(button, busy, label)`：统一按钮忙碌状态。

标准响应的 `data` 对象会被解包为调用结果，同时保留 `success/message/request_id`。业务脚本不得自行判断多套错误字段。

## SSE 层 `DataFinderSSE`

文件：`app/static/js/sse-client.js`

`stream(url, {method, json, signal, onEvent})` 只接受 `meta/delta/card/audio/error/done`。未知事件、非 JSON 数据、缺少 `done`、标准 `error` 事件都会产生 `RequestError`。用户工作台和模型测试页均使用此入口。

## 卡片层 `DataFinderCards`

文件：`app/static/js/card-renderer.js`

`render(card)` 支持 `text/kpi/table/line_chart/bar_chart/pie_chart/weather/music/news/image/video`。所有文本通过 `textContent` 写入；媒体 URL 仅允许 HTTP/HTTPS。兼容期可读取旧 weather/analysis 数据，新增接口必须使用 `type + data` 标准结构。

## 变更规则

1. 先更新 `API_CONTRACT.md` 或 `EVENT_SCHEMA.md`。
2. 更新公共模块，不在单个页面新增特殊解析分支。
3. 更新 `test/frontend_contract_test.js` 和 `test/test_frontend_contract.py`。
4. 再迁移业务页面。
