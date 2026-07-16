# 成员 D 项目交付验收说明

本文件只覆盖项目代码，不包含官网、海报、PPT 和演示视频。

## 1. 用户工作区

- `/index`：模型选择、数字员工、任务历史、会话切换、新建、删除、PDF 导出。
- `/api/chat/stream`：SSE `meta/delta/card/audio/done/error`，客户端可停止并在失败后重新生成。
- 文本使用 DOM 白名单 Markdown 渲染，不执行原始 HTML；数据卡、表格、图表、音频使用对应渲染器。
- 语音播报使用浏览器中文 SpeechSynthesis；服务返回音频 URL 时显示原生播放器。

## 2. PDF 导出

- 路由：`GET /api/conversations/<id>/export.pdf`，仅允许导出当前用户自己的会话。
- ReportLab 使用系统中文字体或 `DATAFINDER_PDF_FONT`，包含标题、用户、时间、消息角色、员工/模型、表格、折线/柱状/饼图、内嵌图片和页码。
- 长消息、长表格自动分页。外部媒体不由服务端抓取，以避免 SSRF；可信 data URL 图片可直接嵌入。

## 3. 管理工作台与大屏

- `/api/admin/dashboard`：用户、会话、模型调用、采集、成功率、风险、员工、任务、错误和服务状态。
- `/admin/screens/intelligence`：本地 ECharts-GL 三维地球、趋势、来源、活动、词频、热点与风险证据链。
- `/admin/screens/opinion`：风险统计、趋势、来源比例、最新预警、规则分析、处置状态与备注。
- 页面具备暂停自动刷新、手动刷新、全屏、键盘焦点、文字状态、数据表替代和 reduced-motion 处理。

## 4. 人脸登录

- 用户工作区录入 5—8 帧并验证当前密码；允许重录和删除档案。
- 登录页按输入用户名验证唯一档案，执行单人脸、清晰度、多帧一致性、活体变化和相似度检查。
- 超级管理员可在用户管理页控制全局开关及单用户开关；未录入用户不能凭人脸登录。
- 画面仅在浏览器内缩放后随本次请求提交，数据库只保存归一化特征，不保存原始照片。

## 5. 手势识别

- 项目本地 `gesture_recognizer.task` 由 MediaPipe 加载，不依赖 CDN。
- 胜利手势 → `@天气`；握拳 → `@音乐`；张开手掌 → `@新闻`。
- 3—7 帧中过半一致才触发；相同用户相同手势 5 秒冷却；触发事件写入 `gesture_events`。
- 返回数字员工编号并激活现有工作区员工选择，最终仍走统一问数 API。

## 6. 数据与依赖

- 迁移 `007_member_d_features.sql` 新增 `system_settings`、`face_profiles`、`gesture_events`、`opinion_alerts`。
- 运行依赖锁定 `reportlab==5.0.0`、`mediapipe==0.10.32`；所有安装、运行和验证均使用项目 `venv`。
- ECharts、ECharts-GL、手势模型均在 `app/static/dist` 或 `app/services/models` 本地提供。
