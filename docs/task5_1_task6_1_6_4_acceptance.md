# 任务 5.1、6.1—6.4 验收说明

## 实现映射

| 老师要求 | v0.5 实现 |
|---|---|
| 数字员工上传一个或多个 Markdown | 管理表单 `multipart/form-data` + 多选 `.md`，按员工 ID 独立目录保存 |
| OpenAI API + SSE | 上游 `/chat/completions` 使用 `stream=true`，用户端 `/api/chat/stream` 转发增量事件 |
| 耗时与 token | 每条助手消息持久化 `elapsed_seconds`、usage，并显示“响应 x.xx s · n token” |
| 配置名称与数据卡片 | 卡片由后台员工 `response_mode` 决定，前端显示员工 `name` 而不是 `code` |
| AI 查询数据库 | 安全意图服务调用 `AnalyticsRepository` 的固定只读统计 |
| 统计、分析、展示、关系、图谱、报告 | KPI、来源柱状、七日折线、深采环形、来源关系图与报告表 |
| 安全要求 | 不接收/回显用户 SQL，SQL 与 Prompt 注入在服务层统一拒绝 |
| 虚拟环境 | `setup.ps1` 创建项目 `venv`；`run.ps1`、测试、编译均使用其中的 Python |

## 真实与演示边界

- 天气来自 `wttr.in` 公开 JSON；城市参数经过 URL 编码。
- 仓库分析读取当前 SQLite 中真实记录，空仓库会如实显示 0 或空状态。
- 普通对话需要管理员配置可用模型和运行环境 API Key，不内置任何密钥或伪造模型回答。
- Canvas 图表是类似 ECharts 的本地实现，不依赖 CDN；只有识别到分析意图时生成。

## 验收命令

```powershell
.\venv\Scripts\python.exe -m py_compile app.py app\controllers\*.py app\models\*.py app\services\*.py
.\venv\Scripts\python.exe -m pytest -q
powershell -ExecutionPolicy Bypass -File .\tools\package.ps1
```
