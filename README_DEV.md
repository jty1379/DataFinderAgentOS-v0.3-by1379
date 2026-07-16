# DataFinderAgentOS v0.3 开发指南

## 环境

建议 Python 3.11，在项目目录创建独立虚拟环境：

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

本项目不会自动解析 `.env` 文件；可在 PowerShell 中设置变量，或由 IDE 的环境配置加载 `.env`。开发环境最低无需额外变量即可运行，Cookie Secret 会写入已忽略的 `config/runtime_secret.txt`。

```powershell
$env:APP_ENV = "development"
python app.py
```

默认地址为 `http://127.0.0.1:10010/`，管理端为 `/admin/login`。首次空库会创建 `admin` 演示账号；课堂默认密码见主 README，生产部署必须立即修改。

## 架构

```text
app/controllers/      HTTP 参数、页面和响应
app/services/         业务规则与跨仓储编排
app/repositories/     数据访问稳定入口
app/models/           兼容期 Repository 实现与数据转换
app/database/         连接、迁移、种子数据
app/core/             异常、响应契约、日志、权限
config/               development/testing/production 配置
```

后台权限维护控制器已按 `users / roles / features / menus / modules` 拆开。新增后台领域应创建独立文件，不再恢复集中式 `admin.py`。

## 数据库变更

1. 新建递增且唯一的 `app/database/migrations/NNN_name.sql`。
2. 每个文件只执行一次；已经写入 `schema_migrations` 的文件禁止修改。
3. SQL 迁移必须可在一个事务内完成，失败由 runner 回滚。
4. 仅将可重复执行的默认数据放进 `seed.py`。

## 配置

`APP_ENV` 支持 `development`、`testing`、`production`。生产环境禁止 Debug，且必须提供至少 32 字符的 `COOKIE_SECRET`。业务代码不得直接读取 `os.environ`，动态模型密钥使用 `SETTINGS.secret_from_env()`。

完整接口、字段和事件契约见 `docs/`。协作规则见 `CONTRIBUTING.md`。
