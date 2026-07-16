# 第一阶段重构记录

## 2026-07-16

- 将集中式 `app/controllers/admin.py` 拆为 users、roles、features、menus、modules 五个领域控制器，保持路由和稳定导入名。
- 增加 `app/repositories` 稳定数据访问边界，将菜单 Repository 实体迁出大型 RBAC 文件；其余旧实现通过兼容门面逐步迁移。
- 新增用户与 RBAC Service，注册、认证、管理员落地页等业务规则脱离 HTTP Handler。
- 将数据库拆为 connection、migration_runner、seed；引入带版本、名称、时间和 SHA-256 校验和的正式迁移记录。
- 支持空库初始化、旧库缺失字段升级、迁移事务回滚和幂等系统种子数据。
- 建立 development/testing/production Settings，收口环境变量读取并校验生产 Debug 与 Cookie Secret。
- 新增统一业务异常、JSON/分页/SSE/卡片契约、权限入口和 request_id。
- 将核心启动输出改为滚动分类日志；新增 app/error/security/collection/model/audit/migration 日志类别。
- SSE 事件统一为 meta/delta/card/audio/error/done，并同步用户工作台解析。
- 增加 `.env.example`、开发/部署文档、公共契约文档、协作规范和 black/ruff 配置。

本轮按任务委托人的明确要求未执行自动测试、编译检查、备份或 Git 操作；验收前仍应由团队按 `README_DEV.md` 执行完整回归。

## 2026-07-16 · A/B/C 缺口闭环

- C：统一采集任务状态、数据库进度/日志、取消/重试/恢复、来源运行指标、仓库筛选/详情/重采/批量/导出/去重及稳定问数接口。
- B：数字员工绑定接口并实时读取 Skills，数据库问数工具真实生效；TTS 统一数据库配置与调用日志；多模态改为异步、数据库任务和真实 OpenAI 兼容生图。
- A：会话完整筛选与真实分页、风险/耗时/Token 明细、归档/批删/PDF；系统设置类型校验并接入业务；统一舆情幂等服务与管理操作审计。
- 外部源代码漏洞扫描和报告不在本轮执行。

## 2026-07-16 · 成员 D 前端契约

- 新增统一请求、错误、XSRF、超时与 request_id 展示模块 `DataFinderApp`。
- 新增只接受冻结事件名并验证完成状态的 `DataFinderSSE`。
- 新增覆盖十一类契约卡片的 `DataFinderCards`，保留旧天气和分析结果兼容转换。
- 用户工作台、模型对话和数字员工预览接入公共模块，业务脚本不再直接调用 Fetch 或重复解析 SSE。
- 新增前端公共契约文档及 Node/Pytest 回归检查。
- 用户可见“深度采集”收敛为公开网页“正文补全”，增加静态 HTML/JSON-LD 备用提取器；音乐数字员工改为站内公开片段播放器，手势打开摄像头后自动连续识别。
- 模型统计详情增加摘要和规范表格，控制台图例独立对齐；审计日志退出业务导航和路由；数智地球使用可辨识大陆轮廓并标注真实地区新闻点。
