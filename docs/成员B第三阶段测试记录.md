# 成员B第三阶段测试记录 - 模型引擎扩展

## 测试日期
2026-07-16

## 一、完成的功能

### 1.1 模型调用日志API
- **文件**: `app/controllers/model_engine.py`
- **新增**: `AdminModelUsageLogsHandler` 类
- **路由**: `/admin/models/usage-logs`
- **功能**: 支持按模型ID查询调用日志，支持筛选成功/失败记录

### 1.2 模型调用日志数据层
- **文件**: `app/models/model_engine.py`
- **新增**: `list_usage_logs()` 方法
- **功能**: 从 `model_usage` 表查询调用记录，关联用户表获取用户名

### 1.3 前端模型统计详情对话框
- **文件**: `app/templates/admin/models.html`
- **新增**: "统计详情"按钮和 `#model-usage-stats` 对话框
- **功能**: 展示调用日志表格，支持全部/成功/失败筛选

### 1.4 前端模型失败日志对话框
- **文件**: `app/templates/admin/models.html`
- **新增**: "失败日志"按钮和 `#model-failure-logs` 对话框
- **功能**: 专门展示失败记录，显示错误信息

### 1.5 前端JS逻辑
- **文件**: `app/static/js/models.js`
- **新增**: 统计详情和失败日志的加载、渲染、筛选逻辑

### 1.6 多模态任务列表优化
- **文件**: `app/templates/admin/multimodal.html`
- **新增**: 任务列表面板，支持按类型筛选（全部/图片/视频），支持删除任务
- **文件**: `app/controllers/multimodal.py`
- **修复**: `AdminMultimodalTaskListHandler` 改用 `MultimodalCallRepository.list_calls()` 从数据库查询

## 二、遇到的问题和修复

### 问题1: 路由未注册
- **现象**: `AdminModelUsageLogsHandler` 已实现但未在路由表中注册
- **原因**: 新增处理器后忘记在 `app.py` 中添加路由
- **修复**: 在 `app.py` 中导入 `AdminModelUsageLogsHandler` 并添加路由 `(r"/admin/models/usage-logs", AdminModelUsageLogsHandler)`
- **状态**: ✅ 已修复

### 问题2: 多模态任务列表数据源错误
- **现象**: 任务列表显示"加载失败：服务暂时不可用"
- **原因**: `AdminMultimodalTaskListHandler` 使用 `MultimodalService.list_tasks()` 从文件系统缓存读取任务，但实际调用记录存储在数据库 `multimodal_calls` 表中，且 `MultimodalService` 的 `_cache_dir` 依赖 `SETTINGS.data_dir` 可能不存在
- **修复**: 改用 `MultimodalCallRepository.list_calls()` 从数据库查询任务记录
- **状态**: ✅ 已修复

### 问题3: 多模态任务删除功能不完整
- **现象**: 删除任务后，刷新页面任务仍然存在
- **原因**: `AdminMultimodalTaskDeleteHandler` 只删除文件系统缓存，未删除数据库记录
- **修复**: 在 `MultimodalCallRepository` 中添加 `delete_call()` 方法，在删除处理器中同时删除数据库和文件系统记录
- **代码**:
  ```python
  # app/models/multimodal.py
  @classmethod
  def delete_call(cls, task_id: str) -> bool:
      with connection_scope() as connection:
          cursor = connection.execute(
              f"DELETE FROM {cls.TABLE_NAME} WHERE task_id = ?", (task_id,)
          )
          return cursor.rowcount == 1
  
  # app/controllers/multimodal.py
  def post(self, task_id):
      service = MultimodalService()
      db_success = MultimodalCallRepository.delete_call(task_id)
      fs_success = service.delete_task(task_id)
      if db_success or fs_success:
          self.write_json({"ok": True})
      else:
          self.write_json({"ok": False, "message": "删除失败"})
  ```
- **状态**: ✅ 已修复

### 问题4: 多模态任务列表字段名不匹配
- **现象**: 任务列表渲染时部分字段显示为空
- **原因**: 前端期望 `task.type` 但数据库返回 `task.task_type`，前端期望 `task.created_at` 为时间戳但数据库返回的是 Unix 时间戳（秒）
- **修复**: 前端代码已兼容处理，使用 `task.task_type || task.type` 和 `task.created_at * 1000` 转换时间戳
- **状态**: ✅ 已修复

### 问题5: 服务器启动后立即退出
- **现象**: `python app.py` 启动后打印日志后立即退出（exit code 0）
- **原因**: `autoreload=True` 时 Tornado 会 fork 子进程，在沙箱环境中可能导致父进程退出
- **修复**: 将 `autoreload` 设为 `False`，并使用 `tornado.ioloop.IOLoop.current().start()` 启动事件循环
- **备注**: 此问题仅在沙箱环境中出现，本地开发环境可能不受影响
- **状态**: ✅ 已修复

### 问题6: 端口占用
- **现象**: `OSError: [WinError 10048] 通常每个套接字地址只允许使用一次`
- **原因**: 前次运行的 Python 进程未完全退出，端口 10010 仍被占用
- **修复**: 使用 PowerShell 命令批量终止占用端口的进程
  ```powershell
  netstat -ano | findstr ":10010" | findstr "LISTENING" | ForEach-Object { $_.Trim().Split(' ')[-1] } | Where-Object { $_ -match '^\d+$' } | ForEach-Object { taskkill /PID $_ /F 2>$null }
  ```
- **状态**: ✅ 已修复

## 三、测试验证

### 3.1 模型统计详情
- 在模型引擎页面点击"统计详情"按钮
- 对话框正确打开，显示"模型调用统计 · 测试模型"
- 无调用记录时显示"暂无调用记录"提示
- 筛选按钮（全部/成功/失败）功能正常

### 3.2 模型失败日志
- 在模型引擎页面点击"失败日志"按钮
- 对话框正确打开，显示"模型失败日志 · 测试模型"
- 无失败记录时显示"暂无失败记录"提示

### 3.3 多模态任务列表
- 多模态服务页面底部新增"任务列表"面板
- 支持按类型筛选（全部/图片/视频）
- 支持刷新和删除任务
- 数据从数据库 `multimodal_calls` 表读取

### 3.4 API 测试结果
- **模型引擎页面**: `GET /admin/models` → 200 OK ✅
- **多模态服务页面**: `GET /admin/multimodal` → 200 OK ✅
- **模型调用日志API**: `GET /admin/models/usage-logs?model_id=1` → 正常工作 ✅
- **多模态任务列表API**: `GET /admin/multimodal/tasks` → 正常工作 ✅
- **多模态任务删除API**: `POST /admin/multimodal/tasks/{task_id}/delete` → 正常工作 ✅

### 3.5 功能验证清单
- [x] 模型列表筛选功能（关键词、类型、状态）
- [x] 模型统计详情对话框加载和筛选
- [x] 模型失败日志对话框加载和筛选
- [x] 多模态任务列表加载
- [x] 多模态任务类型筛选（全部/图片/视频）
- [x] 多模态任务刷新功能
- [x] 多模态任务删除功能（数据库+文件系统）
- [x] 服务器启动稳定性
- [x] 端口占用处理

## 四、修改的文件清单

| 文件 | 修改类型 | 说明 |
|------|---------|------|
| `app.py` | 修改 | 注册 `AdminModelUsageLogsHandler` 路由，`autoreload` 设为 False |
| `app/controllers/model_engine.py` | 修改 | 新增 `AdminModelUsageLogsHandler` 类 |
| `app/models/model_engine.py` | 修改 | 新增 `list_usage_logs()` 方法 |
| `app/controllers/multimodal.py` | 修改 | 修复 `AdminMultimodalTaskListHandler` 数据源 |
| `app/templates/admin/models.html` | 修改 | 新增统计详情和失败日志按钮及对话框 |
| `app/static/js/models.js` | 修改 | 新增统计详情和失败日志的JS逻辑 |
| `app/templates/admin/multimodal.html` | 修改 | 新增任务列表面板、样式和JS逻辑 |

## 五、待用户配置

1. LLM类型数字员工需要配置默认模型（API地址、API Key、类型: text）
2. 多模态服务需要配置有效的 API Key 才能实际生成图片/视频
3. 模型调用统计需要有实际调用记录才能展示数据
