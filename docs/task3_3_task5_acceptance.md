# 任务 3.3 / 任务 5 实现与验收映射

## 迭代边界

- 昨日已完成：任务 3.1 的“瞭望采集”改名、A 区水平布局、B 区规则参数可视化，以及任务 3.2 的采集结果入仓、仓库搜索/分页/详情/删除和深采标识。
- 今日新增：任务 3.3 真实深度采集；任务 5 管理侧数字员工。
- 明确不做：用户侧 `@数字员工` 调用、天气卡片、真实问数对话和定时任务。

## 任务 3.3

| 老师要求 | 实现位置 | 验收方式 |
|---|---|---|
| 点击深度采集打开悬浮窗 | `warehouse.html`、`warehouse.js` | 单条按钮创建任务并打开原生 dialog |
| 任务、进度、状态、步骤 | `deep_collection.py` Repository/Service | 轮询 `/admin/warehouse/deep-tasks/{id}`，展示 0—100 进度和六步轨道 |
| 派发采集专员与详细情况 | `digital_employees` 系统种子、任务外键 | 面板显示员工名称、@调度名、职责、当前步骤与任务模式 |
| 执行日志与结果 | `deep_collection_logs/results` | 每一步写日志，成功写正文/摘要/元数据，失败写错误 |
| 已采集查看详情 | `/admin/warehouse/deep-results/{item_id}` | “深采数据”读取数据库最新结果 |
| 批量与更新采集 | `create_tasks(..., update=...)` | 本页复选、批量深采、更新深采；重复首次采集自动跳过 |
| 数据持久化 | SQLite 迁移版本 4 | 任务、日志、历次结果与仓库正文分别存表 |
| 采集专员可用 | `DeepCollectionService.collector_employee()` | 缺失、停用或无采集能力时拒绝创建任务 |

## 任务 5

| 老师要求 | 实现位置 | 验收方式 |
|---|---|---|
| CRUD、列表、分页 | `/admin/agents` | 搜索、类型/状态筛选、8 条分页、新增/设置/启停/删除 |
| LLM 或 LLM+Crawl4AI | `digital_employee.py`、`DigitalEmployeeService` | 默认/指定模型、必填 Prompt、模板、技能、采集开关与配置 |
| HTTP/HTTPS API | 同上 | GET/POST、公开 URL、参数模板、请求头、超时、JSON/卡片模式 |
| @xxx 调度 | `mention` 唯一字段 | 页面显示 `@调度名`，服务按员工 ID 加载同一配置 |
| 后台预览 | `/admin/agents/preview` | 模型文本或 API JSON/数据卡片，失败显示真实原因 |
| 深采分派 | 系统 `collection_specialist` | `@采集专员` 绑定每个深采任务 |
| v0.3 当时暂不开发用户侧 | 历史版本边界 | 该边界已在 v0.4 任务 6 中解除，详见 `task3_4_task6_acceptance.md` |

## 自动验收

执行：

```powershell
python -m pytest -q
```

专项文件 `test/test_v03_employees_deep.py` 覆盖系统员工保护、两类配置校验、CRUD/分页、深采成功持久化、重复/更新任务、页面渲染、XSRF 和任务 JSON。
