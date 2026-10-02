# Django 后端部署指南

本指南将帮助你将 Django 后端部署到公网服务器。

> **安全状态（2026-09-29）**：本文包含历史 PythonAnywhere 示例，仍设置 `BLOG_LOCAL_MODE=true` / `AGENT_SECURITY_ENFORCED=false`，而且该平台路径尚未通过当前 V2 安全启动门和 `check --deploy`。请勿照本文示例公开部署；生产部署方案以 [Blog设计文档V2.0](Blog设计文档V2.0.md) 与 [缺陷跟踪表V2.0](缺陷跟踪表V2.0.md) 的 B-003 为准，待 TLS 与安全配置修复并通过验收后再启用。

## PostgreSQL/pgvector 迁移账号与运行账号（B-013）

Railway 或其他生产环境必须先用**迁移账号**执行 Django migrations，再以**运行账号**启动 API/worker。migration job 需要 `CREATE EXTENSION vector`（若扩展尚未由平台预装）、创建/修改表和索引、迁移历史向量/列的权限；通常使用数据库 owner 或单独受控的一次性 migration role。应用 `DATABASE_URL` 不应复用该高权限账号。

推荐部署步骤：

1. 在 Railway Variables 中分别保存 `MIGRATION_DATABASE_URL`（owner/migration role）与 `DATABASE_URL`（应用 runtime role），不要把连接串写入仓库、镜像或日志。
2. 在一次性 migration job/部署前置步骤中运行 `DATABASE_URL="$MIGRATION_DATABASE_URL" python manage.py migrate --noinput`；核对 `python manage.py showmigrations agent_api token_blacklist`，特别是 `0020`、`0028`、`0031` 和 B-011 的 blacklist 包迁移。缺少 blacklist 表时不要启动新版认证接口。
3. API/worker 服务仅保留 runtime `DATABASE_URL`，并设置 `RUN_MIGRATIONS=false`，避免容器 entrypoint 让受限运行账号执行 migration。数据库表结构先由上述 migration job 更新完成，再启动应用。
4. runtime role 至少有数据库 `CONNECT`、schema `USAGE`、应用业务表所需的最小 SELECT/INSERT/UPDATE/DELETE 及相关 sequence 权限。对 `agent_api_vectorindex` 需要 SELECT/INSERT/UPDATE/DELETE；不授予 schema CREATE、表 owner、ALTER、扩展安装权限。`search`/`upsert`/删除不会创建或修改 schema。

缺表、B-012 identity 列落后或 pgvector 类型/运算符缺失时，向量接口返回安全 503 migration 提示并记录 operation/SQLSTATE；不会在请求期间执行 DDL 或回退为 SQLite/hash。收到此错误应停止流量切换、用 migration 凭据检查迁移状态并补跑 migrations。保留迁移前 PostgreSQL 备份；不要反向执行 `0020`（其 reverse 会删除向量表）。需要恢复时先恢复到隔离数据库、检查迁移状态与向量数后再安排恢复，避免直接覆盖线上数据库。

CI 中 `.github/workflows/ci.yml` 的 `backend-postgres` job 在临时空库执行 migrations，再运行 6 个 PostgreSQL 集成测试：SQL spy 零 DDL、缺 schema 报错、无 CREATE/ALTER 的临时 runtime role 读写/更新/删除、迁移索引、workspace 隔离、B-012 同维异模型过滤等。本机 Docker daemon 和 `psql` 不可用，本轮真库 job 未实跑；默认与安全 SQLite 完整 suite 各 143/143、Ruff/Black/迁移检查通过但不代表 PostgreSQL 权限验收已通过。

## 📋 方案对比

| 特性 | PythonAnywhere（免费） | Railway（$5免费额度） | Render（$7/月） |
|------|----------------------|---------------------|----------------|
| 数据库 | SQLite | PostgreSQL ✅ | PostgreSQL ✅ |
| Redis/Celery | ❌ 不支持 | ✅ 支持 | ✅ 支持 |
| 部署难度 | ⭐ 简单 | ⭐⭐ 中等 | ⭐⭐ 中等 |
| 国内访问 | ✅ 可访问 | ✅ 可访问 | ✅ 可访问 |
| 自定义域名 | ❌ 付费 | ✅ 免费 | ✅ 免费 |

---

## 🚀 方案 1：PythonAnywhere（推荐新手）

### 1. 注册账号

1. 访问 [www.pythonanywhere.com](https://www.pythonanywhere.com)
2. 点击 **"Create a Beginner account"**（免费）
3. 验证邮箱完成注册

### 2. 上传代码

登录后，点击页面顶部的 **"Dashboard"**，然后点击 **"Bash"** 打开终端：

```bash
# 克隆仓库
git clone https://github.com/yuanbin2/IPBS.git
cd IPBS/backend
```

### 3. 创建虚拟环境

```bash
# 创建虚拟环境
mkvirtualenv --python=/usr/bin/python3.10 ipbs-env

# 安装依赖
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn
```

### 4. 配置环境变量

创建 `.env` 文件：

```bash
cat > .env << 'EOF'
DJANGO_SECRET_KEY=replace-with-a-private-token-url-safe-48-chars-or-longer
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=yourusername.pythonanywhere.com
BLOG_LOCAL_MODE=true
APP_TIMEZONE=Asia/Shanghai
DATABASE_URL=sqlite:///home/yourusername/IPBS/backend/db.sqlite3
AGENT_SECURITY_ENFORCED=false
EOF
```

**重要**：将 `yourusername` 替换为你的 PythonAnywhere 用户名！

### 5. 初始化数据库

```bash
# 运行迁移
python manage.py migrate

# 创建管理员账号
python manage.py createsuperuser

# 收集静态文件
python manage.py collectstatic --noinput
```

### 6. 配置 Web 应用

1. 点击页面顶部的 **"Web"** 标签
2. 点击 **"Add a new web app"**
3. 确认域名（如 `yourusername.pythonanywhere.com`）
4. 选择 **"Manual configuration"**
5. 选择 **Python 3.10**

### 7. 配置 WSGI

在 Web 页面中，点击 **"WSGI configuration file"** 链接，将内容替换为：

```python
import os
import sys

# 添加项目路径
path = '/home/yourusername/IPBS/backend'
if path not in sys.path:
    sys.path.insert(0, path)

# 设置 Django 设置模块
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

# 启动 Django
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

### 8. 配置虚拟环境

在 Web 页面的 **"Virtualenv"** 部分，输入：
```
/home/yourusername/.virtualenvs/ipbs-env
```

### 9. 配置静态文件

在 Web 页面的 **"Static files"** 部分，添加：

| URL | Directory |
|-----|-----------|
| `/static/` | `/home/yourusername/IPBS/backend/staticfiles` |
| `/media/` | `/home/yourusername/IPBS/backend/media` |

### 10. 启动应用

点击页面顶部的绿色 **"Reload"** 按钮。

访问 `https://yourusername.pythonanywhere.com` 查看你的 API！

---

## 🚀 方案 2：Railway（推荐生产环境）

### 1. 注册 Railway

1. 访问 [railway.app](https://railway.app)
2. 使用 GitHub 账号登录
3. 获得 $5 免费额度

### 2. 安装 Railway CLI

```bash
npm install -g @railway/cli
```

### 3. 登录并部署

```bash
# 登录
railway login

# 进入后端目录
cd backend

# 初始化项目
railway init

# 添加 PostgreSQL
railway add postgresql

# 添加 Redis
railway add redis

# 设置环境变量
railway variables set DJANGO_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')
railway variables set DJANGO_DEBUG=false
railway variables set BLOG_LOCAL_MODE=false
railway variables set APP_TIMEZONE=Asia/Shanghai
railway variables set AGENT_SECURITY_ENFORCED=true
railway variables set DJANGO_HTTPS_TERMINATED=true
railway variables set DJANGO_SECURE_SSL_REDIRECT=true
railway variables set DJANGO_SECURE_HSTS_SECONDS=3600
railway variables set DJANGO_SESSION_COOKIE_SECURE=true
railway variables set DJANGO_CSRF_COOKIE_SECURE=true

# 部署
railway up
```

Railway provides TLS at its public edge and forwards `X-Forwarded-Proto: https`; its `RAILWAY_PUBLIC_DOMAIN` system variable is added to Django `ALLOWED_HOSTS`. The settings trust that proxy signal, force HTTPS, and set Secure cookies. HSTS starts with a one-hour max-age and does not include subdomains or preload until the live domain has been checked. See [Railway public networking](https://docs.railway.com/networking/public-networking), [Railway request headers](https://docs.railway.com/networking/public-networking/specs-and-limits), and the [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).

For asynchronous document ingestion and evaluation batches, run a separate Railway service from the same repository/image with the same `DATABASE_URL`, `RABBITMQ_URL`, and `REDIS_URL` variables as the web service. Set its start command to `celery -A config worker --loglevel=INFO --queues=celery,documents,evaluations --concurrency=1`. Without this worker and a healthy RabbitMQ broker, evaluation batches remain queued; Redis is used for the result backend outside local mode. This worker setup has not yet been exercised on Railway.

### 4. 绑定域名（可选）

在 Railway 项目设置中：
1. 点击 **"Settings"**
2. 找到 **"Domains"**
3. 点击 **"Generate Domain"** 获取免费子域名
4. 或者添加自定义域名

---

## 🔧 前后端连接配置

部署后端后，需要更新前端的 API 地址：

### 方法 1：环境变量

推荐将 SPA 与 `/api/` 放在同一站点，通过反向代理或 Django 的 SPA 路由提供；此时前端 API 地址留空：
```
VITE_API_BASE_URL=
```

B-011 的 refresh Cookie 使用 SameSite=Lax；若前端放在另一个顶级域名，单靠 CORS 允许名单不能让 Cookie 正常发送。跨站方案需先设计并验证 SameSite=None+Secure、明确的 `DJANGO_CSRF_TRUSTED_ORIGINS`、精确的 `DJANGO_CORS_ALLOWED_ORIGINS` 和凭据请求，当前尚未支持为推荐生产路径。部署时先迁移 blacklist 表，再发布前后端同版本，实测登录、刷新、退出与旧客户端升级；确认回滚与旧客户端使用情况后才关闭旧 JSON refresh 接口。

### 方法 2：修改前端代码

编辑 `frontend/src/api/client.ts`，修改 API 基础 URL：

```typescript
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'https://yourusername.pythonanywhere.com'
```

然后重新部署前端：
```bash
cd frontend
npm run build
npx wrangler pages deploy dist --project-name=ipbs
```

---

## 📊 部署验证

### 检查后端是否运行

```bash
# 访问 API 根路径
curl https://yourusername.pythonanywhere.com/api/

# 或者访问管理后台
https://yourusername.pythonanywhere.com/admin/
```

### 检查前端是否连接

1. 访问 https://ipbs.pages.dev
2. 点击 "开始使用"
3. 尝试登录或注册

---

## 🐛 常见问题

### 1. 500 错误

检查 PythonAnywhere 的 **"Error log"**：
- Web 页面 → 点击 **"Error log"** 链接
- 查看具体错误信息

### 2. 静态文件 404

确保：
1. 运行了 `python manage.py collectstatic`
2. Web 页面中配置了正确的静态文件路径

### 3. 数据库错误

如果使用 SQLite：
```bash
# 重新运行迁移
python manage.py migrate
```

### 4. CORS 错误

确保 `settings.py` 中添加了前端域名：
```python
CORS_ALLOWED_ORIGINS = [
    'https://ipbs.pages.dev',
    'https://41e6d5c4.ipbs.pages.dev',
]
```

---

## 📚 更多资源

- [PythonAnywhere 帮助文档](https://help.pythonanywhere.com)
- [Railway 文档](https://docs.railway.app)
- [Django 部署清单](https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/)

---

## 🎉 部署完成！

部署成功后，你将拥有：

- ✅ **前端**：https://ipbs.pages.dev（Cloudflare Pages）
- ✅ **后端**：https://yourusername.pythonanywhere.com（PythonAnywhere）
- ✅ **管理后台**：https://yourusername.pythonanywhere.com/admin/

现在你可以：
1. 在前端注册账号
2. 登录使用所有功能
3. 通过管理后台管理数据

祝你部署顺利！🚀

## 文档索引后台处理（B-014）

部署 Web、Celery worker 和 Celery Beat 时必须共用同一 `DATABASE_URL`、`RABBITMQ_URL`、知识附件存储与 embedding 环境变量。worker 至少监听 `documents` 队列，Beat 每 30 秒投递 outbox 恢复任务：

```bash
celery -A config worker --loglevel=INFO --queues=celery,documents,evaluations
celery -A config beat --loglevel=INFO
```

发布迁移 `0032_durable_document_ingestion_outbox` 前先备份 PostgreSQL。上传/重建返回的 UUID 可在授权 workspace 下通过 `/api/agent/tasks/<uuid>/` 查询；最终状态为 `completed`、`failed` 或 `superseded`，失败响应显示受控 `failure_code`。临时 broker 故障由 outbox 有限重试，最多 5 次后需 operator/admin 发起重新处理（新代次）。监控 `DocumentIngestionJob` 中 pending/queued/processing/retry 的持续时间、过期租约、failed 数量和错误码；不能仅依据 Celery result backend 或 HTTP 202 判断处理成功。

回滚与恢复步骤：

1. 停止上传/文章发布写入，暂停 Beat 和所有 documents worker；确认没有 processing 租约仍有效。
2. 以只读方式检查每个文档的 `active_ingestion_generation`、活动切片数和状态；对照 `chunk_count` 并记录失败 job。先对数据库、知识附件原件及 PostgreSQL pgvector 数据做一致时间点备份。
3. 优先回滚应用代码但保留 `0032` schema；旧切片在成功切换时已于同一事务内清理，因此当前活动代次仍是完整索引。观察检索和 workspace 隔离后再恢复写入。
4. 只有确需反向迁移时，先在隔离恢复副本确认每个文档活动代次唯一且 `(document,chunk_index)` 不冲突，再停止所有新版任务、回滚 Django migration。不要删除 outbox、源文件或 pgvector 行作为回滚手段。
5. 恢复备份先还原到隔离数据库/附件存储，比较文档/job/chunk/vector 计数，抽样检索及工作空间隔离通过后再切换连接；保留故障前副本以便二次恢复。

真实 Railway 上的 worker 可见性、RabbitMQ 故障恢复、持久附件共享、重启后重试与完整恢复演练仍需发布前实测；本地 eager 或 mock broker 不构成该验收证据。
