# DataFinderAgentOS - 数据采集和问数系统实现文档

## 项目概述

本文档描述了 DataFinderAgentOS v0.3 中**数据采集和问数系统**的完整实现。该系统包括三个真实的数据采集源、完善的采集任务管理、增强的数据仓库功能、自然语言问数系统以及舆情安全分析。

## 核心模块

### 1. 采集源管理 (Collection Sources)

#### 三个真实数据源

项目配置了三个完整的公开数据源：

1. **百度新闻** (`baidu_news`)
   - 基础URL: `https://www.baidu.com/s`
   - 采集方式：基于关键词的搜索结果
   - 解析器：`baidu_news` (专用解析器)
   - 参数配置：支持分页、固定参数

2. **四川大学新闻网** (`scu_news`)
   - 基础URL: `https://news.scu.edu.cn/`
   - 采集方式：通用链接提取
   - 解析器：`generic_links`
   - 特点：校园官方新闻源

3. **36氪创投热点** (`kr36_trending`)
   - 基础URL: `https://www.36kr.com/search`
   - 采集方式：创投行业动态
   - 解析器：`generic_links`
   - 特点：融资信息与行业洞察

#### 采集规则管理

每个数据源都关联了预配置的采集规则：

```python
RuleRepository.create(
    source_id=source_id,
    name="规则名称",
    keyword_param="word",      # 关键词参数名
    page_param="pn",           # 分页参数名
    page_start=0,              # 分页起始值
    page_step=10,              # 分页步长
    page_size=12,              # 单页结果数
    parser_type="baidu_news",  # 解析器类型
    enabled=True
)
```

### 2. 采集任务管理系统 (Collection Task Service)

#### 位置
`app/services/collection_task.py`

#### 核心功能

**CollectionTaskService** 类提供三种采集模式：

1. **批量采集** (`create_batch_task`)
   - 支持多页采集
   - 自动失败重试（最多3次）
   - 集成安全分析

2. **单条采集** (`create_single_task`)
   - 单页面采集
   - 快速响应

3. **深度采集** (`create_deep_task`)
   - 针对仓库项目
   - 支持数字员工处理

#### 关键特性

- **进度追踪**: `get_task_progress()`
- **失败重试**: 最多重试3次，间隔1秒
- **错误恢复**: try-except 保证采集不崩溃
- **安全分析**: 自动评估内容风险等级

```python
# 创建批量采集任务
task_id = CollectionTaskService.create_batch_task(
    rule_id=1,
    keyword="AI技术",
    pages=3,
    user_id=user_id
)

# 执行任务
success, failed = await CollectionTaskService.execute_batch_task(
    task_id=task_id,
    rule_dict=rule,
    keyword="AI技术",
    pages=3
)

# 查询进度
progress = CollectionTaskService.get_task_progress(task_id)
```

### 3. 数据仓库扩展 (Warehouse Enhancement)

#### 新增字段

在 `warehouse_items` 表中添加了以下字段：

1. **keywords** (TEXT, 500字符)
   - 从内容提取的关键词
   - 支持逗号分隔

2. **risk_level** (TEXT)
   - 取值：`low`, `normal`, `high`, `critical`
   - 默认：`normal`
   - 用于风险分类

3. **matched_words** (TEXT, 500字符)
   - 匹配的敏感词汇
   - 安全分析结果

4. **security_analysis** (TEXT, JSON)
   - 完整的舆情分析结果
   - 包含风险分数、建议等

#### WarehouseRepository 新方法

```python
# 批量删除
WarehouseRepository.batch_delete(item_ids)

# 更新风险等级
WarehouseRepository.update_risk_level(
    item_id, 
    risk_level="high",
    security_analysis={...}
)

# 更新关键词
WarehouseRepository.update_keywords(item_id, keywords, matched_words)

# 数据去重（基于URL）
WarehouseRepository.deduplication()

# 按风险等级筛选
WarehouseRepository.get_by_risk_level(risk_level="high")

# 获取统计摘要
stats = WarehouseRepository.get_summary_stats()
# 返回: {
#   "total_count": 1000,
#   "deep_count": 100,
#   "critical_count": 5,
#   "high_count": 50,
#   "normal_count": 900,
#   "low_count": 45
# }
```

### 4. 舆情安全分析 (Security Analysis)

#### 位置
`app/services/security_analysis.py`

#### SecurityAnalyzer 类

自动分析采集内容的风险等级：

```python
risk_level, analysis = SecurityAnalyzer.analyze(
    title="标题",
    summary="摘要",
    content="正文内容"
)

# 返回格式
{
    "risk_level": "high",           # 风险等级
    "risk_score": 7.5,              # 风险分数 (0-10)
    "matched_words": ["敏感词1"],   # 匹配的敏感词
    "analysis": "检测到敏感词...",   # 分析说明
    "suggestions": ["建议人工审查"]  # 处理建议
}
```

#### 敏感词库

分为三个等级：

- **critical**: 恐怖、极端、暴力、违法、犯罪等
- **high**: 政治、敏感、抗争、游行等
- **medium**: 投资风险、环境污染等

#### 采集流程集成

安全分析已集成到 `execute_batch_task()` 中：

1. 采集数据后立即分析
2. 保存风险等级和分析结果
3. 支持风险等级筛选和告警

### 5. 自然语言问数系统 (Query Intent System)

#### 位置
`app/services/query_intent.py`

#### 扩展的问法支持

系统现支持 **7+ 类** 问数：

1. **今天采集统计**
   ```
   "今天采集了多少条数据？"
   "采集了多少条新闻？"
   ```
   返回：今日采集数、周均数等

2. **各来源分布**
   ```
   "各来源分别有多少条新闻？"
   "来源分别采集了多少条？"
   ```
   返回：各源采集量柱状图

3. **采集失败率**
   ```
   "哪个来源失败率最高？"
   "采集失败情况分析"
   ```
   返回：来源成功率排序表

4. **高风险内容**
   ```
   "最近有哪些高风险内容？"
   "敏感内容预警"
   ```
   返回：风险分布图 + 高风险项目表

5. **关键词频率**
   ```
   "哪个关键词出现频率最高？"
   "热词排行"
   ```
   返回：关键词出现频率排序

6. **采集性能**
   ```
   "各来源平均采集耗时是多少？"
   "采集速度分析"
   ```
   返回：各源耗时排序表

7. **综合报告**
   ```
   "数据分析报告"
   "给我一份简报"
   ```
   返回：多维度综合分析

#### AnalyticsRepository 新方法

```python
# 日采集计数
AnalyticsRepository.daily_collection_count()

# 数据源性能统计
AnalyticsRepository.source_performance()
# 返回: [{
#   "label": "百度新闻",
#   "avg_time": 2.5,       # 平均耗时秒
#   "success_count": 100,
#   "total_count": 105,
#   "success_rate": 95.24
# }]

# 风险等级分布
AnalyticsRepository.risk_level_distribution()

# 高风险项目
AnalyticsRepository.high_risk_items(limit=20)

# 关键词频率统计
AnalyticsRepository.keyword_frequency(limit=20)
```

#### 安全机制

- SQL注入防护：检测SQL关键字和操作符
- 提示词注入防护：检测越权相关关键词
- 所有查询都是预定义的只读操作

### 6. API 接口

#### 仓库管理接口

**GET /admin/warehouse/risk-analysis**
```json
{
  "ok": true,
  "stats": {
    "total_count": 1000,
    "critical_count": 5,
    "high_count": 50,
    ...
  }
}
```

**GET /admin/warehouse/high-risk**
```json
{
  "ok": true,
  "items": [...],
  "risk_level": "high",
  "count": 50
}
```

**POST /admin/warehouse/batch-delete**
```json
{
  "item_ids": [1, 2, 3],
  "ok": true,
  "deleted": 3,
  "message": "已删除3条数据"
}
```

**POST /admin/warehouse/deduplication**
```json
{
  "ok": true,
  "deleted": 42,
  "message": "去重完成，删除了42条重复数据"
}
```

## 数据库迁移

新增迁移文件：`app/database/migrations/007_warehouse_extensions.sql`

添加了4个新列和2个索引：

```sql
ALTER TABLE warehouse_items ADD COLUMN keywords TEXT;
ALTER TABLE warehouse_items ADD COLUMN risk_level TEXT DEFAULT 'normal';
ALTER TABLE warehouse_items ADD COLUMN matched_words TEXT;
ALTER TABLE warehouse_items ADD COLUMN security_analysis TEXT DEFAULT '{}';

CREATE INDEX idx_warehouse_risk_level ON warehouse_items(risk_level);
CREATE INDEX idx_warehouse_keywords ON warehouse_items(keywords);
```

## 测试

### 测试文件

1. **test_collection_sources.py**
   - 测试三个真实数据源的创建和管理
   - 测试采集规则的CRUD操作

2. **test_warehouse_operations.py**
   - 测试批量删除、数据去重
   - 测试风险等级更新、关键词更新
   - 测试统计摘要功能

3. **test_query_intent_advanced.py**
   - 测试7+种问数意图识别
   - 测试SQL注入和提示词注入防护
   - 测试各类型的分析结果结构

### 运行测试

```bash
# 运行所有新增测试
python -m pytest test/test_collection_sources.py -v
python -m pytest test/test_warehouse_operations.py -v
python -m pytest test/test_query_intent_advanced.py -v

# 运行特定测试
python -m pytest test/test_collection_sources.py::TestCollectionSources::test_three_real_sources_present -v
```

## 使用示例

### 完整采集流程

```python
from app.services.collection_task import CollectionTaskService
from app.models.source import RuleRepository

# 1. 获取采集规则
rule = RuleRepository.get(rule_id=1)

# 2. 创建批量采集任务
task_id = CollectionTaskService.create_batch_task(
    rule_id=1,
    keyword="人工智能",
    pages=2,
    user_id=1
)

# 3. 异步执行任务
import asyncio
success, failed = await CollectionTaskService.execute_batch_task(
    task_id=task_id,
    rule_dict=rule,
    keyword="人工智能",
    pages=2
)

# 4. 查询进度
progress = CollectionTaskService.get_task_progress(task_id)
print(f"状态: {progress['status']}, 结果数: {progress['result_count']}")

# 5. 查询仓库风险统计
from app.models.warehouse import WarehouseRepository
stats = WarehouseRepository.get_summary_stats()
print(f"高风险项: {stats['high_count']}, 关键项: {stats['critical_count']}")
```

### 问数系统使用

```python
from app.services.query_intent import QueryIntentService

# 自然语言问数
questions = [
    "今天采集了多少条数据？",
    "各来源分别有多少条新闻？",
    "最近有哪些高风险内容？",
    "哪个关键词出现频率最高？",
]

for question in questions:
    try:
        result = QueryIntentService.analyze(question)
        if result:
            print(f"问: {question}")
            print(f"意图: {result['data']['intent']}")
            print(f"答: {result['data']['narrative']}")
    except Exception as e:
        print(f"查询失败: {e}")
```

## 架构特点

1. **异步采集**：使用async/await支持高并发
2. **错误恢复**：采集失败不会中断整个任务
3. **自动重试**：失败项目自动重试（最多3次）
4. **风险分析**：自动进行舆情评估
5. **数据去重**：支持基于URL的自动去重
6. **安全防护**：SQL/提示词注入保护
7. **灵活查询**：支持7+种自然语言问法

## 文件清单

### 新建文件
- `app/services/collection_task.py` - 采集任务管理服务
- `app/services/security_analysis.py` - 舆情安全分析
- `app/database/migrations/007_warehouse_extensions.sql` - 数据库迁移
- `test/test_collection_sources.py` - 采集源测试
- `test/test_warehouse_operations.py` - 仓库操作测试
- `test/test_query_intent_advanced.py` - 问数系统测试

### 修改文件
- `app/models/warehouse.py` - 扩展仓库模型
- `app/models/analytics.py` - 扩展分析查询
- `app/services/query_intent.py` - 扩展问数系统
- `app/controllers/warehouse.py` - 新增API端点
- `app/database/seed.py` - 添加三个真实数据源
- `app.py` - 注册新路由

## 后续扩展建议

1. **更多数据源**：添加RSS源、API源等
2. **智能聚类**：识别相似新闻进行自动聚类
3. **舆情预警**：设置风险等级阈值自动告警
4. **数据导出**：支持Excel/PDF报告导出
5. **实时监测**：定时任务自动采集更新
6. **模型优化**：使用ML模型优化风险评分

