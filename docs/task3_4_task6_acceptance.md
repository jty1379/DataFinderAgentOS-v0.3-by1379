# 任务 3.4 与任务 6 验收映射

## 任务 3.4 · 采集专员深度采集

| 老师要求 | 项目实现 | 验收证据 |
|---|---|---|
| 采集标题、正文等详细数据 | `DeepCollectionService._fetch` 保存标题和最多 200,000 字符 Markdown | Python 教程真实联调提取 19,876 字符 |
| 由采集专员完成 | 深采任务固定关联系统 `collection_specialist` | 任务日志记录 `@采集专员` |
| 必须使用 Crawl4AI | `AsyncWebCrawler + BrowserConfig + CrawlerRunConfig` | metadata 记录 `parser=crawl4ai`、版本 0.8.5 |
| 安装依赖与环境 | `requirements.txt`、`setup.ps1`、项目 `venv` | `crawl4ai-setup` 已安装 Chromium |
| 保存到数据仓库 | `deep_collection_results` 与 `warehouse_items.content` | Repository 专项测试 |

## 任务 6 · 用户侧系统

| 老师要求 | 项目实现 |
|---|---|
| 登录注册与后台闭环 | 前后台共用 `users`、`roles` 和状态验证 |
| A 区 Logo 与标题 | 左栏 DF 标识和“瞭望与问数系统” |
| B 区模型切换 | 读取启用文本模型并默认选择后台默认模型 |
| C 区任务列表 | 自动标题、会话/消息持久化、点击读取历史 |
| D/E 对话与输入区 | 浅色扁平对话区、固定响应式输入区和 loading |
| `/` 或 `@` 数字员工 | 命令面板、键盘控制、员工标签和服务端调度 |
| 员工模型优先 | 专属模型优先，不可用时回退系统默认模型 |
| 天气数据 | `@天气` 调用 wttr.in JSON 并显示天气卡片 |
| 自适应与沉浸式 | 桌面双栏、手机抽屉、无装饰性光球与过度渐变 |

## 真实联调记录

- 日期：2026-07-14。
- 虚拟环境：`DataFinderAgentOS\venv`，Python 3.12.1。
- Crawl4AI：0.8.5，Playwright Chromium 安装完成。
- 深采地址：`https://docs.python.org/3/tutorial/index.html`。
- 结果：标题 `The Python Tutorial`，正文 19,876 字符，parser 为 crawl4ai。
- 天气地址：`https://wttr.in/成都?format=j1&lang=zh`。
- 结果：HTTP 200，返回当前气象与未来三日数据；界面统一按用户输入显示“成都”，来源标注 wttr.in。
