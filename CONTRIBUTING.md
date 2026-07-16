# 协作规范

## 代码边界

- Controller 只读取参数、调用 Service、渲染页面或返回响应。
- Service 承担校验、权限规则、状态流转和跨 Repository 协作，不依赖 Tornado Handler。
- Repository 承担参数化 SQL、持久化与数据行转换，不执行页面跳转。
- 新表或字段只能新增 `app/database/migrations/NNN_name.sql`，已执行迁移不得修改。
- 公共字段变化先更新 `docs/API_CONTRACT.md`、`DATABASE_SCHEMA.md` 或 `EVENT_SCHEMA.md`。

## 命名与格式

- 文件、函数、变量使用 `snake_case`，类使用 `PascalCase`，常量使用 `UPPER_SNAKE_CASE`。
- UTF-8、4 空格缩进，公开 Service 方法写 Docstring 和类型注解。
- 建议单函数不超过 80 行，单文件不超过 500 行。
- 提交前执行 `python -m black app config test`、`python -m ruff check app config test` 和 `python -m pytest`。

## 分支与提交

- 功能分支从稳定开发分支创建，命名 `feature/<domain>-<topic>` 或 `fix/<domain>-<topic>`。
- 一次提交只处理一个可说明的变更，提交信息使用 `type(scope): summary`。
- 禁止提交数据库、`.env`、运行密钥、日志、缓存、虚拟环境和采集临时数据。
