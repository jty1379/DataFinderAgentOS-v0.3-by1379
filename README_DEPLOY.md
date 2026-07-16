# DataFinderAgentOS v0.3 部署指南

## 生产配置

部署账户应使用独立虚拟环境，并通过进程管理器注入环境变量：

```text
APP_ENV=production
DEBUG=false
HOST=127.0.0.1
PORT=10010
DATABASE_PATH=<绝对路径>
COOKIE_SECRET=<至少32位随机值>
XSRF_COOKIES=true
LOG_LEVEL=INFO
LOG_DIR=<可写日志目录>
MODEL_API_KEY_ENV=OPENAI_API_KEY
OPENAI_API_KEY=<由密钥管理服务注入>
```

生产环境必须把 Tornado 放在 HTTPS 反向代理之后。代理应保留 `X-Request-ID`，关闭 SSE 路由响应缓冲，并限制请求体大小。应用默认只监听 `127.0.0.1`，如需改变应同步配置防火墙。

## 发布步骤

1. 安装 `requirements.txt`，不要复制开发机虚拟环境。
2. 准备可写的数据库与日志目录，不要把数据库放在源码仓库。
3. 注入环境变量并启动 `python app.py`；启动会自动执行未应用迁移和幂等种子数据。
4. 首次部署后立即修改默认管理员密码。
5. 检查 `logs/migration.log` 与 `logs/error.log`，确认没有迁移或配置错误。

## 回滚与备份

发布前应由部署系统备份 SQLite 数据库。代码回滚不能自动撤销已执行数据库迁移；涉及不可逆结构变更时必须新增显式回滚方案或从备份恢复。日志、数据库、密钥文件、`.env`、缓存和上传数据均不进入源码包。
