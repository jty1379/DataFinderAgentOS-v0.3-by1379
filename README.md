# 瞭望与问数系统 DataFinderAgentOS v0.3

基于 Tornado + SQLite 的政务数据采集与智能问数系统。v0.3 已集成权限、采集、仓库、模型引擎、数字员工、Crawl4AI 深采、OpenAI 兼容 SSE 问答、真实仓库统计分析、数据报告、关系图谱及数字员工 Markdown 资料。

团队开发请先阅读 [开发指南](README_DEV.md)、[部署指南](README_DEPLOY.md) 和 [协作规范](CONTRIBUTING.md)。冻结的 API、数据库与 SSE 契约位于 `docs/`。

## 技术栈

- Python 3.12 / Tornado 6.5.7 / ReportLab 5
- Crawl4AI 0.8.5 / Playwright Chromium
- MediaPipe 0.10.32 / OpenCV（多帧手势与人脸活体校验）
- SQLite3 + Repository 模式
- Tornado Template
- Layui 2.9.8（主要组件）
- Bootstrap 5.3.8（响应式辅助）
- 原生 CSS / JavaScript / Canvas / 本地 ECharts + ECharts-GL

Layui、Bootstrap 和字体均位于 `app/static/dist/`，后台界面断网时仍可加载本地 UI 资源。外部新闻采集和模型对话本身需要目标服务可访问。

## 快速开始

```powershell
cd DataFinderAgentOS
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

`setup.ps1` 会在项目目录创建 `venv`、安装锁定依赖并执行 `crawl4ai-setup`；`run.ps1` 只调用 `venv\Scripts\python.exe`。项目运行、测试和依赖安装均不得改用全局 Python。

浏览器访问：

- 用户端：<http://localhost:10010/>
- 管理端：<http://localhost:10010/admin/login>
- 演示超级管理员：`admin / 123456`

首次启动会自动创建或迁移数据库，初始化系统角色、功能、菜单和演示超级管理员。数据库、Cookie Secret、模型密钥、虚拟环境和缓存不进入源码 ZIP。

## v0.3 已实现范围

### 用户侧问数工作台

- 注册和登录直接复用后台用户表、角色、状态与密码验证，停用用户无法登录
- 浅色企业/政务双栏工作台：左侧系统标识、默认模型切换与任务记录；右侧为对话区和固定输入区
- 首次提问自动生成任务标题；会话和消息分别写入 `user_conversations`、`user_messages`
- 点击任务记录可读取当前用户自己的历史消息，其他用户会话返回 404
- 输入 `/` 或 `@` 打开数字员工命令面板，支持键盘上下选择、Enter 确认和 Esc 关闭
- 数字员工优先使用专属模型；专属模型不可用时回退系统默认模型
- 内置 `@天气` 调用 wttr.in 的 JSON 接口，并收敛为当前温度、体感、湿度、风况及三日预报卡片
- 普通模型问答按 OpenAI `/chat/completions` + `stream=true` 请求，上游增量通过 `/api/chat/stream` SSE 实时转发
- 每条助手回答显示响应秒数、真实 token 用量和模型/数字员工的配置名称
- 自然语言识别仓库概览、来源分布、近七日趋势、深采进度、关系图谱和分析报告意图
- 统计只执行服务端固定只读 SQL；拒绝用户 SQL、提示词泄露和越权注入，不向前端暴露真实 SQL
- 报表按命中意图渲染 KPI、柱状图、折线图、环形图、关系图和明细表；普通闲聊不强制生成图表
- 未配置大模型时如实提示，并仍允许使用无需模型的 API 数字员工
- 支持安全 Markdown、回答语音播报、音频结果播放器、停止生成、失败重试、当前/指定会话删除与 PDF 导出
- 支持人脸档案录入/重录/删除、指定账号多帧活体人脸登录，并始终保留密码登录兜底
- 支持 MediaPipe 多帧手势快捷调度：胜利手势查询天气、握拳调度音乐、张开手掌调度新闻；同手势具有 5 秒冷却

### 管理工作台与双大屏

- 工作台指标全部读取 SQLite：可用用户、今日会话、模型调用、今日采集、采集成功率、高风险预警和启用数字员工
- 最近任务、模型错误、系统服务状态和安全基线均来自实际记录或明确的运行配置，不填充演示数字
- 数智大屏使用本地 ECharts/ECharts-GL 展示三维地球来源点、来源分布、采集/模型/用户趋势、词频、热点和风险分布
- 舆情大屏由用户消息和仓库内容规则命中生成可追溯预警，支持处理中、已解决、误报及处理备注
- 两块大屏提供刷新、暂停刷新、全屏、图表数据表替代和 reduced-motion 降级
- 用户管理可由超级管理员全局启停人脸登录，或对已录入用户单独启停

### 权限管理

- 用户、角色、功能、菜单四个管理模块和动态侧边栏
- 用户、角色和功能列表采用“上方搜索/操作、中间列表、下方分页”的管理布局，固定每页 20 条；用户支持批量启用、禁用和删除
- 普通用户与管理侧账号隔离
- 默认 `admin` 超级管理员账号保护：用户名、角色、状态不可修改且不可删除，仅本人验证当前密码后可以修改自己的密码
- 内置系统管理员角色不可编辑、授权、停用或删除
- 功能支持一级、二级结构；角色授权使用 Layui Tree，禁用功能不能继续授权或生成菜单
- 菜单支持排序和按角色预览，左侧导航由角色授权、功能状态与菜单状态共同生成
- 只有默认超级管理员可以执行用户、角色、功能、菜单四个权限配置模块的写操作，其他管理角色在这些模块只读
- 瞭源管理、瞭望采集、数据仓库和模型引擎是业务模块；拥有对应 `role_feature` 的管理角色可以使用和维护
- Handler 服务端权限校验，不能通过隐藏菜单或伪造表单绕过

### 瞭源管理与瞭望采集

- 维护采集来源、请求地址、可用状态、请求头和可视化查询参数
- 按关键词和规则发起新闻采集，支持分页参数
- 采集结果采用响应式卡片列表展示，每页 12 条
- 请求超时、无结果、目标站异常均返回明确状态，不将失败伪装成真实数据
- 请求头只保存业务所需字段，不需要也不允许复制个人 Cookie

### 数据仓库

- 选择或全选采集结果并批量入库
- 搜索、分页、详情查看和删除
- 重复数据幂等处理与深度采集标记
- 单条、批量与更新深采；已深采数据可查看最新持久化正文
- 深采浮窗实时展示进度、状态、六步执行链、派发员工、日志和结果摘要
- 任务、日志及每次更新采集结果分别持久化，服务重启时未完成任务会被安全标记为中断
- 深采只接收公开 HTTP/HTTPS 来源，进入 Crawl4AI 前执行内网与凭据地址校验
- 由系统 `@采集专员` 强制调用 Crawl4AI 无头 Chromium，提取标题、正文 Markdown、最终地址、状态码和链接统计
- 详细正文最多保存 200,000 字符，结果、任务进度与执行日志均持久化到数据仓库相关表

### 数字员工

- 数字员工新增、修改、删除、启停、搜索、分类与每页 8 条分页
- 支持模型 / Crawl4AI 型：默认或指定模型、必填系统提示词、任务模板、技能和网页采集配置
- 支持 HTTP API 型：GET/POST、公开接口地址、参数模板、超时和 JSON/数据卡片响应
- 统一使用 `@调度名`；后台预览明确显示真实返回或配置错误，不生成伪结果
- 内置系统“采集专员”不可删除或停用，负责数据仓库深度采集
- 用户侧通过 `/` 或 `@` 调度已启用员工；后台系统采集专员不暴露给普通用户
- 新增/编辑员工可多选上传 UTF-8 `.md` 资料；每名员工隔离到 `data/dgUser/<id>/`，调用时只作为事实背景补充 Prompt

### 模型引擎

- 管理 OpenAI API 兼容模型配置
- 支持文本、图像、音频、视频、多模态和嵌入分类
- 模型新增、修改、删除、查询、分类筛选和默认模型设置
- 配置系统提示词、温度、top_p、上下文数和最大 token
- 通过独立服务层进行模型对话，Controller 不直接拼装外部 SDK 调用
- SSE 流式返回模型响应，并在模型卡片中展示 token 用量
- API Key 不回显、不写入前端脚本，也不进入提交包

## 安全基线

- Secure Cookie + HttpOnly + SameSite=Lax
- 所有 POST 表单启用 XSRF
- SQL 使用 `?` 参数占位
- PBKDF2-SHA256 100,000 轮加盐哈希
- 外部采集设置超时、响应限制与请求头过滤
- 模型和采集权限同时覆盖页面地址与数据接口

## 测试

```powershell
.\venv\Scripts\python.exe -m unittest discover -s test -v
```

自动测试使用临时 SQLite 数据库。外部采集、深度采集与模型/API 员工均通过模拟响应验证解析和异常处理，不把第三方站点实时可用性作为单元测试通过条件。

完整回归当前为 48 项，覆盖 Markdown multipart 上传与隔离、OpenAI SSE 分片与 usage、仓库统计意图、SQL/Prompt 注入拒绝、分析卡片和用户端 SSE 事件。

2026-07-14 另完成两项真实联调：Crawl4AI 从 Python 官方教程提取 19,876 个 Markdown 正文字符并记录版本 0.8.5；`https://wttr.in/成都?format=j1&lang=zh` 成功返回当前天气和三日预报。第三方实时服务仍可能受网络、限流或页面结构影响，运行失败时系统会明确显示错误。

权限回归测试额外覆盖老师任务 2.1—2.4：`useradmin / admin888` 可登录后台并只读查看用户管理；伪造请求不能改删或批量影响 `admin`；只有 `admin` 本人验证旧密码后能修改自己的密码；系统管理员角色不可改；右上角账号下拉菜单具有明确的前景色、背景色与键盘焦点。

### 百度新闻联调结论

2026-07-13 使用关键词“四川”、`pn=0`，以无 Cookie、无 Authorization 的公开浏览器兼容请求头访问：

`https://www.baidu.com/s?tn=news&rtt=1&bsst=1&cl=2&word=四川&pn=0`

原始请求返回 HTTP 200，响应约 542,548 字节，未跳转验证码，并解析到 10 个 `news-title_*` 标题。随后使用项目内 `CollectorService.collect`、临时数据库默认百度规则和 12 条上限复测，得到 `RULES 1`、`RESULTS 10`，前三条均为真实标题和 HTTPS 地址，证明 v0.2 的规则读取、请求、解析链路已实际通过。对照请求仅设置最小 User-Agent 时被重定向到 `wappass` 图形验证码。

结论：2026-07-13 项目内百度新闻采集链路实测可用，共返回 10 条；但它依赖公开浏览器兼容头并受站点风控影响，不能视为稳定生产接口。程序必须检测验证码、重定向、空结果和页面结构变化并如实反馈；不得记录、提交或要求用户提供任何 Cookie。

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `DATAFINDER_PORT` | `10010` | HTTP 端口 |
| `DATAFINDER_DEBUG` | `0` | 设置为 `1` 开启调试 |
| `DATAFINDER_DB_PATH` | `database/finderos.db` | 数据库路径 |
| `DATAFINDER_COOKIE_SECRET` | 自动生成 | 可从环境注入 Cookie Secret |
| `OPENAI_API_KEY` | 空 | 默认模型服务密钥；也可由模型配置引用运行环境 |
| `OPENAI_BASE_URL` | 空 | OpenAI API 兼容服务地址 |
| `DATAFINDER_LLM_MODEL` | 空 | 默认模型名称 |

不要把 `.env`、API Key、Cookie、真实抓包请求头或运行时密钥提交到源码包。

## 项目结构

```text
DataFinderAgentOS/
├── app.py                    # Tornado 入口，端口 10010
├── requirements.txt         # 固定 Tornado、LiteLLM 与 Crawl4AI 版本
├── requirements-dev.txt     # 项目 venv 内的测试依赖
├── setup.ps1 / run.ps1      # 项目 venv 安装与启动入口
├── config/                   # 端口、数据库、Cookie 与模型运行配置
├── database/                 # 运行时 SQLite 数据，仅提交 README
├── data/dgUser/              # 按员工编号隔离的运行时 Markdown 资料
├── docs/                     # AI 协作开发文档
├── test/                     # Repository 与 HTTP 集成测试
├── tools/package.ps1         # 安全打包脚本
└── app/
    ├── controllers/          # 认证、管理、采集、仓库、深采、员工和模型请求
    ├── models/               # SQLite Repository
    ├── services/             # 外部采集、深采编排、数字员工与模型服务
    ├── templates/            # 用户侧模板
    │   └── admin/            # 管理侧模板
    └── static/               # 自定义资源与本地组件库
```

## 打包

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\package.ps1
```

脚本默认在项目上一级生成不覆盖旧作业包的收尾归档：

`零界-齐语林-瞭望与问数系统v0.3源码.zip`

ZIP 根目录固定为 `DataFinderAgentOS/`，并自动排除 venv、数据库、密钥、缓存、日志、浏览器测试产物和旧 ZIP。

项目署名：零界 · 齐语林
