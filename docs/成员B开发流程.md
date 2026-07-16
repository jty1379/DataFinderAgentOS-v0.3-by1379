# 成员B：AI模型与数字员工负责人 - 开发流程

## 一、岗位定位

负责模型引擎、数字员工、接口管理、Skills管理、语音合成等核心AI能力的开发与集成。

## 二、主要负责目录

| 层级 | 文件/目录 | 状态 | 说明 |
|------|-----------|------|------|
| Controller | app/controllers/model_engine.py | ✅ 已存在 | 模型配置管理、SSE对话 |
| Controller | app/controllers/digital_employee.py | ✅ 已存在 | 数字员工管理、预览 |
| Controller | app/controllers/interface.py | ❌ 待创建 | 接口管理 |
| Controller | app/controllers/skill.py | ❌ 待创建 | Skills管理 |
| Service | app/services/llm.py | ✅ 已存在 | OpenAI兼容模型服务 |
| Service | app/services/digital_employee.py | ✅ 已存在 | 数字员工调度服务 |
| Service | app/services/employee_knowledge.py | ✅ 已存在 | Prompt资料管理 |
| Service | app/services/tts.py | ❌ 待创建 | 语音合成服务 |
| Service | app/services/multimodal.py | ❌ 待创建 | 生图/生视频服务 |
| Model | app/models/model_engine.py | ✅ 已存在 | 模型配置与用量统计 |
| Model | app/models/digital_employee.py | ✅ 已存在 | 数字员工配置Repository |
| Model | app/models/interface.py | ❌ 待创建 | 接口配置Repository |
| Model | app/models/skill.py | ❌ 待创建 | Skills配置Repository |

## 三、开发阶段规划

### 第一阶段：基础架构完善（优先）

#### 1.1 创建接口管理模块

**目标**：实现接口的增删改查、测试、日志查看功能

**文件创建**：
- `app/models/interface.py` - 接口配置Repository
- `app/controllers/interface.py` - 接口CRUD、测试、日志查看

**接口字段设计**：
| 字段 | 类型 | 说明 |
|------|------|------|
| interface_name | VARCHAR(100) | 接口名称 |
| interface_code | VARCHAR(50) | 接口编码（唯一） |
| api_url | TEXT | 接口地址 |
| request_method | VARCHAR(10) | 请求方法（GET/POST） |
| request_headers | TEXT(JSON) | 请求头模板 |
| request_params | TEXT(JSON) | 请求参数模板 |
| response_path | TEXT | 响应数据路径 |
| timeout_seconds | INTEGER | 超时时间 |
| retry_count | INTEGER | 重试次数 |
| enabled | BOOLEAN | 启用状态 |
| description | TEXT | 接口说明 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

**功能要求**：
- 新增接口
- 编辑接口
- 删除接口
- 启用和停用
- 测试接口
- 查看调用日志
- 接口绑定数字员工
- JSON响应路径提取
- GET和POST请求
- 超时控制

**安全要求**：
- API Key使用环境变量
- 不明文显示密钥
- URL进行SSRF检查
- 禁止访问私网和回环地址
- 限制响应大小
- 过滤敏感请求头

#### 1.2 创建Skills管理模块

**目标**：实现技能增强的配置与管理

**文件创建**：
- `app/models/skill.py` - Skills配置Repository
- `app/controllers/skill.py` - Skills增删改查、绑定数字员工

**技能字段设计**：
| 字段 | 类型 | 说明 |
|------|------|------|
| skill_name | VARCHAR(100) | 技能名称 |
| skill_code | VARCHAR(50) | 技能编码（唯一） |
| description | TEXT | 技能说明 |
| trigger_condition | TEXT | 触发条件 |
| system_prompt | TEXT | 系统提示词 |
| tool_config | TEXT(JSON) | 工具配置 |
| enabled | BOOLEAN | 启用状态 |
| employee_ids | TEXT(JSON) | 关联数字员工ID列表 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

**功能要求**：
- 绑定技能前后，数字员工行为有区别
- 技能能够调用工具或改变提示词
- 后台可新增、编辑、启用、停用
- 至少一个Skills功能可现场演示

**推荐技能**：
1. 数据库问数技能
2. 新闻摘要技能
3. 敏感内容分析技能

#### 1.3 创建语音合成服务

**目标**：实现文本转语音功能

**文件创建**：
- `app/services/tts.py` - TTSService

**功能要求**：
| 功能 | 说明 |
|------|------|
| 文本转语音 | 将模型回复转换为语音 |
| 用户开关 | 支持用户开启或关闭自动播放 |
| 默认声音设置 | 支持后台设置默认声音 |
| 长文本分段 | 支持长文本分段处理 |
| 失败降级 | 生成失败时继续显示文字 |
| 音频缓存 | 支持音频缓存 |
| 返回audio_url | 返回audio_url供前端播放 |

#### 1.4 创建多模态服务

**目标**：实现生图、生视频功能

**文件创建**：
- `app/services/multimodal.py` - 生图/生视频服务

**生图流程**：
```
用户输入提示词
→ 识别为生图任务
→ 调用图像模型
→ 保存任务记录
→ 返回图片地址
→ 前端显示图片
```

**生视频流程**：
```
用户输入提示词
→ 调用视频模型
→ 保存任务ID
→ 轮询结果
→ 返回视频地址
→ 前端播放
```

**要求**：
- 不返回模拟地址
- 失败时给出明确错误
- 演示时可使用低分辨率和短时长节省费用
- 生成记录写入数据库

### 第二阶段：数字员工实现（核心）

**目标**：实现至少6个数字员工

#### 2.1 数字员工清单

| 序号 | 数字员工 | 类型 | 实现方式 | 依赖 |
|------|---------|------|---------|------|
| 1 | 天气专员 | 接口型 | 调用wttr.in API | 接口管理 |
| 2 | 随机音乐 | 接口型 | 调用公开音乐API | 接口管理 |
| 3 | 新闻专员 | 数据库/接口型 | 查询数据仓库 | 成员C数据仓库 |
| 4 | 川哥 | 大模型型 | 校园问答提示词 | LLMService |
| 5 | 文案写作助手 | 大模型型 | 文案生成提示词 | LLMService |
| 6 | 数据分析师 | 问数型 | 调用成员C问数服务 | 成员C问数接口 |

#### 2.2 调用示例

```
@天气 成都天气
@随机音乐
@新闻 最近有什么热点
@川哥 川大江安校区有什么学习建议
@文案写作助手 写一段活动宣传文案
@数据分析师 最近一周采集趋势如何
```

#### 2.3 实现要求

**关键实现要求**：
- 数字员工从数据库读取配置
- 不允许全部写成if/elif硬编码
- 统一由DigitalEmployeeService调度
- 每个员工记录调用次数和失败次数
- 支持启用、停用和后台测试
- API失败时返回友好提示

**数字员工配置结构**：
| 字段 | 说明 |
|------|------|
| code | 员工编码（weather/music/news/chuan/copywriter/analyst） |
| name | 员工名称 |
| mention | @调度名 |
| employee_type | 类型（llm/api/database） |
| system_prompt | 系统提示词（llm类型） |
| prompt_template | 提示词模板 |
| api_url | 接口地址（api类型） |
| api_method | 请求方法 |
| request_headers | 请求头 |
| request_params | 请求参数 |
| response_mode | 响应模式（json/card） |
| timeout_seconds | 超时时间 |

### 第三阶段：模型引擎扩展

**目标**：完善模型引擎功能，支持多模态模型

#### 3.1 模型类型扩展

| 类型 | 说明 |
|------|------|
| text | 文本生成 |
| image | 图像生成 |
| video | 视频生成 |
| audio | 语音合成 |
| multimodal | 多模态 |
| embedding | 嵌入 |

#### 3.2 功能增强

| 功能 | 说明 |
|------|------|
| 新增模型 | 支持添加新模型配置 |
| 编辑模型 | 支持修改模型配置 |
| 删除模型 | 支持删除模型 |
| 启用停用 | 支持启用/停用模型 |
| 设置默认 | 支持设置默认模型 |
| 测试模型 | 支持后台测试模型 |
| 调用记录 | 记录模型调用次数 |
| Token统计 | 记录Token使用量 |
| 调用耗时 | 记录调用耗时 |
| 失败日志 | 记录失败原因 |

#### 3.3 模型配置字段

| 字段 | 类型 | 说明 |
|------|------|------|
| name | VARCHAR(100) | 模型名称 |
| model_type | VARCHAR(20) | 模型类别 |
| base_url | TEXT | Base URL |
| model_name | VARCHAR(100) | 模型标识 |
| api_key_env | VARCHAR(100) | API Key环境变量 |
| max_tokens | INTEGER | 最大Token |
| timeout_seconds | INTEGER | 超时时间 |
| enabled | BOOLEAN | 启用状态 |
| is_default | BOOLEAN | 是否默认 |
| description | TEXT | 说明 |

### 第四阶段：语音合成播报

**目标**：实现模型回复的语音合成功能

#### 4.1 TTSService实现

**功能要求**：
| 功能 | 说明 |
|------|------|
| 文本转语音 | 将模型回复转换为语音 |
| 用户开关 | 支持用户开启或关闭自动播放 |
| 默认声音设置 | 支持后台设置默认声音 |
| 长文本分段 | 支持长文本分段处理 |
| 失败降级 | 生成失败时继续显示文字 |
| 音频缓存 | 支持音频缓存 |
| 返回audio_url | 返回audio_url供前端播放 |

**技术方案**：
- 使用第三方TTS服务（如百度TTS、阿里云TTS）
- API Key通过环境变量配置
- 支持多种声音选择
- 支持音量、语速调节

#### 4.2 与前端集成

**接口设计**：
```
POST /api/tts/synthesize
参数：
- text: 要转换的文本
- voice: 声音类型（可选）
- speed: 语速（可选）
- volume: 音量（可选）

返回：
- audio_url: 音频文件URL
- duration: 音频时长
```

**前端集成**：
- 成员D负责前端语音播放
- 在对话界面显示播放按钮
- 支持自动播放开关

### 第五阶段：集成测试与优化

**目标**：完成模块间集成，修复bug，优化性能

#### 5.1 跨成员协作

| 协作对象 | 协作内容 |
|---------|---------|
| 成员A | 接口管理权限校验、会话管理集成 |
| 成员C | 数据分析师调用问数服务、新闻专员查询数据仓库 |
| 成员D | 前端语音播放、数字员工交互 |

#### 5.2 测试要求

**单元测试**：
- test_model_*.py - 模型引擎测试
- test_employee_*.py - 数字员工测试
- test_tts_*.py - 语音合成测试

**集成测试**：
- 数字员工调用链路测试
- 模型调用链路测试
- 接口调用链路测试

#### 5.3 性能优化

| 优化项 | 说明 |
|--------|------|
| 缓存优化 | 缓存模型配置、数字员工配置 |
| 异步处理 | 使用异步客户端调用外部API |
| 限流控制 | 限制并发调用数量 |
| 超时控制 | 设置合理的超时时间 |

## 四、Git协作规则

### 4.1 分支管理

**当前分支**：ok-end-netizen

**分支策略**：
- 在ok-end-netizen分支上进行开发
- 完成功能后推送到远程分支
- 需要合并时创建Pull Request

### 4.2 提交格式

```
feat: 新增天气数字员工
feat: 实现接口管理模块
fix: 修复数字员工调度异常
refactor: 重构模型引擎Service
test: 增加问数服务测试
docs: 更新部署说明
security: 修复接口SSRF风险
```

### 4.3 禁止事项

| 禁止项 | 说明 |
|--------|------|
| 提交真实API Key | 使用环境变量配置 |
| 直接向main推送 | 通过Pull Request合并 |
| 提交运行数据库 | 使用迁移文件 |
| 提交venv | 使用.gitignore排除 |
| 提交缓存 | 使用.gitignore排除 |
| 在Controller中堆大量SQL | 使用Repository模式 |
| 修改公共接口不通知 | 修改前通知相关成员 |

### 4.4 合并条件

| 条件 | 说明 |
|------|------|
| 本机运行通过 | 确保代码能正常运行 |
| 原有测试通过 | 确保不破坏现有功能 |
| 新功能有基础测试 | 至少有单元测试 |
| 不包含密钥 | 检查提交内容 |
| 不包含运行数据库 | 检查提交内容 |
| 代码检查 | 由另一名成员完成 |

## 五、验收标准

### 5.1 功能验收

| 验收项 | 要求 |
|--------|------|
| 数字员工数量 | 至少6个真实可用 |
| 接口型员工 | 可后台配置创建 |
| Skills功能 | 至少1个真实生效 |
| 模型测试 | 文本、生图、生视频模型可测试 |
| 语音合成 | 可以生成并播放 |
| 调用日志 | 模型调用和失败有日志 |
| API Key安全 | 不写死，使用环境变量 |

### 5.2 质量验收

| 验收项 | 要求 |
|--------|------|
| 代码风格 | 符合项目规范 |
| 错误处理 | 有友好的错误提示 |
| 安全性 | 通过安全审计 |
| 性能 | 响应时间合理 |
| 测试覆盖 | 关键功能有测试 |

## 六、开发顺序建议

```
阶段一：基础架构完善
1. 接口管理模块（app/models/interface.py + app/controllers/interface.py）
2. Skills管理模块（app/models/skill.py + app/controllers/skill.py）
3. 语音合成服务（app/services/tts.py）
4. 多模态服务（app/services/multimodal.py）

阶段二：数字员工实现
5. 天气专员（接口型）
6. 随机音乐（接口型）
7. 新闻专员（数据库/接口型）
8. 川哥（大模型型）
9. 文案写作助手（大模型型）
10. 数据分析师（问数型）

阶段三：模型引擎扩展
11. 图像生成模型配置
12. 视频生成模型配置
13. 语音合成模型配置

阶段四：语音合成播报
14. TTSService完善
15. 前端集成

阶段五：集成测试与优化
16. 跨模块集成测试
17. Bug修复与性能优化
```

## 七、协作事项

### 7.1 需要其他成员支持

| 成员 | 支持内容 |
|------|---------|
| 成员A | 接口管理权限校验、舆情安全后端集成 |
| 成员C | 数据仓库API、问数服务API |
| 成员D | 语音播放前端、数字员工UI交互 |

### 7.2 提供给其他成员的支持

| 成员 | 提供内容 |
|------|---------|
| 成员C | 数字员工调度接口、数据分析师调用 |
| 成员D | 语音合成API、数字员工API |

## 八、交付物清单

| 交付物 | 说明 |
|--------|------|
| 接口管理模块 | 接口配置CRUD、测试、日志 |
| Skills管理模块 | 技能配置CRUD、绑定数字员工 |
| 语音合成服务 | TTSService |
| 多模态服务 | 生图/生视频服务 |
| 6个数字员工 | 天气、音乐、新闻、川哥、文案、分析师 |
| 模型引擎扩展 | 多模态模型支持 |
| 提示词工程文件包 | 所有数字员工的提示词配置 |
| API和模型配置说明 | 接口和模型的配置文档 |
| 单元测试 | 模型、员工、TTS相关测试 |