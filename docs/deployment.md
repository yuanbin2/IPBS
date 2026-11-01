# 本地运行与 Compose 部署

本页按当前 `start.bat` / `start.sh`、`restart*.ps1`、`docker-compose.yml` 与 Django 配置编写。生产云平台、TLS 代理、对象存储持久性与备份恢复必须按[缺陷跟踪表](缺陷跟踪表V2.0.md)另行实站验收。

## 本地一键模式

根目录 Windows 执行 `start.bat`；Linux/macOS 执行 `chmod +x start.sh && ./start.sh`。脚本安装依赖、构建前端、运行迁移并启动 `127.0.0.1:8001`。显式 `BLOG_LOCAL_MODE=true` 使用 `backend/db.sqlite3`，不启动 Celery/RabbitMQ/Redis 服务；仅适合本地开发和演示。该命令会在本机安装依赖并写入本地数据库，不要在生产工作目录运行。

开发热更新用根目录 `restart.bat` / `restart.sh`：脚本执行迁移与 Django check，启动 API `8001` 和 Vite `5174`。直接运行 `npm --prefix frontend run dev` 默认 Vite `5173`，API 代理目标默认 `8000`，须自行配置环境变量以匹配后端。

## Docker Compose（TLS 代理后）

基础 `docker-compose.yml` 是非本地配置：PostgreSQL、Redis、RabbitMQ 和 RabbitMQ 管理界面**不发布宿主机端口**；Nginx 的 HTTP 入口只绑定宿主机 `127.0.0.1:8080`（可用 `NGINX_PORT` 改端口），供同机 TLS 终止代理转发。不能把该 HTTP 入口直接作为公网地址。代理必须接收公网 HTTPS、把 `Host` 设为实际站点域名，并**覆盖**客户端提供的 `X-Forwarded-Proto` 为单值 `https`。Nginx 仅将这个精确值传给 Django；缺失时 Django 会按 HTTP 请求重定向。启动前用真实代理做重定向、Cookie 与请求头验收。

PowerShell 首次准备（已有 `.env` 时停止，不覆盖）：

```powershell
if (Test-Path .env) { throw '已有 .env；请核对现有配置，不要覆盖' }
Copy-Item .env.example .env
# 在私有配置管理中填入 DJANGO_SECRET_KEY、POSTGRES_PASSWORD、RABBITMQ_PASSWORD，
# 设置 DJANGO_ALLOWED_HOSTS 为站点域名；验证 TLS 代理后设置 DJANGO_HTTPS_TERMINATED=true。
# Compose 的数据库/RabbitMQ 密码须使用 URL 安全字符（字母、数字、-、_）；
# 直接部署另行填写连接 URL 时，才对其中的保留字符做百分号编码。
docker compose config --quiet
# 发布版本号须对应该次构建的 commit 与源码摘要；发布时记录镜像 ID/摘要。
$env:BLOG_RELEASE_ID = '<本次唯一发布版本号>'
docker compose build backend frontend
docker compose up -d postgres redis rabbitmq
# 先在 I-011 的隔离恢复副本上完成迁移和核心验收，再处理目标环境。
docker compose run --rm --no-deps backend python manage.py migrate --plan
docker compose run --rm --no-deps backend python manage.py migrate --noinput
docker compose run --rm --no-deps backend python manage.py collectstatic --noinput
docker compose up -d --no-build backend celery_worker celery_beat frontend
```

POSIX shell 使用 `export BLOG_RELEASE_ID='<本次唯一发布版本号>'`，随后执行同一组 `docker compose` 命令；先检查 `.env` 是否存在，勿覆盖。`docker compose config` 不加 `--quiet` 会显示解析后的环境变量，包括密钥；不要把其输出发到日志或工单。Compose 缺少数据库、RabbitMQ 凭据、允许主机或 TLS 标志时会直接报错，Django 在非本地模式还会拒绝缺少数据库/缓存/消息队列 URL、演示密码、DEBUG、非安全 Cookie 等配置。

镜像使用 `knowledge-agent-backend:${BLOG_RELEASE_ID}` / `knowledge-agent-frontend:${BLOG_RELEASE_ID}`；不得用已覆盖的 `local` 标签当作可回退版本。后端入口默认及 Compose 均**不自动迁移或收集静态文件**，上面的独立迁移命令失败时必须停止发布，不能继续启动新版本。现有环境升级前先按 [I-011 备份恢复说明](I-011-数据生命周期与备份恢复.md)取得同批数据库、媒体和向量索引备份，并在隔离副本上试迁移。只有经审查为旧/新应用均兼容的扩展式迁移才适合与旧实例重叠；其余迁移须进入维护窗口，停止写入和 worker。详见 [I-019 演练与回退步骤](I-019-可重复部署与失败回退演练.md)。

检查状态和日志：

```sh
docker compose ps
docker compose logs --tail=100 backend
docker compose exec backend python manage.py check --deploy
docker compose exec backend python manage.py showmigrations
docker compose exec backend python manage.py migrate --check
```

`/api/health/` 是进程存活检查；`/api/ready/` 还检查数据库连接与是否存在未应用迁移，Compose 后端健康检查使用后者。就绪接口暂不检查 Redis、RabbitMQ、worker 消费或业务数据正确性，必须另做核心接口与任务验收。

浏览器入口是 TLS 代理提供的 `https://<DJANGO_ALLOWED_HOSTS 中的域名>/`，不是 `127.0.0.1:8080` 的明文入口。数据库镜像为 `pgvector/pgvector:0.8.6-pg16`。Compose 使用 PostgreSQL、Redis、RabbitMQ、Celery worker/beat、公开媒体卷和独立私有笔记媒体卷。`BLOG_LOCAL_MODE=false`、`DJANGO_DEBUG=false` 与 `AGENT_SECURITY_ENFORCED=true` 在服务环境中固定；数据库和 RabbitMQ URL 由专用变量构造。直接部署到 Railway 等平台时自行提供 `DATABASE_URL`、`REDIS_URL`、`REDIS_CACHE_URL`、`RABBITMQ_URL`，不得沿用示例凭据。

需要临时从宿主机调试内部服务时，显式加覆盖文件；只发布到本机回环地址，完成调试后移除此覆盖文件并重新应用配置：

```sh
docker compose -f docker-compose.yml -f docker-compose.debug.yml up -d
```

此覆盖文件不改变数据库内的账号权限；同机其他进程仍能访问回环端口，应仅在受控主机上短时使用。平时用 `docker compose exec postgres ...` / `docker compose exec redis ...` 等容器内命令排查，无需开端口。独立的 `start.bat` / `start.sh` 本地开发方式保持不变。

服务健康后可用 `docker compose exec backend python manage.py createsuperuser` 创建 Django 管理账号。公开注册只创建 visitor；不要把公开注册当成授予 operator/admin 的流程。数据库和媒体数据保留在命名卷中。**已有 PostgreSQL/RabbitMQ 数据卷不会因为更改 `.env` 中的初始化密码而自动轮换账号密码**；现存部署要单独制定账号轮换与连接切换步骤，不应仅改变量后重启。

停止服务而保留数据：

```sh
docker compose down
```

`docker compose down -v` 会删除 Postgres、公开媒体和私有笔记媒体等命名卷。本说明不把该命令列作日常清理步骤；执行前必须有经验证的备份和明确数据处置计划。

## 生产安全与未验收项

非本地模式要求高强度 `DJANGO_SECRET_KEY`、显式主机名、PostgreSQL URL、Redis 缓存/结果 URL、RabbitMQ URL、`DJANGO_DEBUG=false`、`AGENT_SECURITY_ENFORCED=true` 和经过验证的 HTTPS/TLS 代理；拒绝常见演示密码、LocMem 缓存和 eager Celery。Cookie 和 CSRF Cookie 必须为 Secure，启用 HTTPS 重定向与 HSTS。非本地模式默认不放行本机 Vite 的跨域来源；需要跨域部署时只填精确 HTTPS 来源和 CSRF 信任来源。`.env.example` 默认关闭 LangSmith/LangChain 外部追踪；启用前先审查私有正文去向与保留策略。Railway 的域名/转发头仍须在真实平台验收。公开博客媒体与私有笔记媒体使用不同访问边界；私有图片目录不得挂载到公开 Nginx 静态路径。

`python scripts/check_compose_boundaries.py` 使用临时合成变量静态检查默认及调试覆盖的端口、缺失密码的失败路径；它不启动容器。`docker compose config --quiet` 和 `manage.py check --deploy` 也只验证配置。还需在隔离部署中验证：

1. `docker compose ps` 全部服务健康；从 backend 容器用短超时 TCP 连接分别检查 `postgres:5432`、`redis:6379`、`rabbitmq:5672`；worker/beat 日志有正常连接记录。
2. `docker compose port postgres 5432`、`docker compose port redis 6379`、`docker compose port rabbitmq 5672` 默认均无发布映射；从另一台隔离测试机探测宿主机 5432/6379/5672/15672 均不可达。加调试覆盖后只从宿主机 `127.0.0.1` 可达，远端仍不可达。
3. TLS 代理正确覆盖 `Host` 和 `X-Forwarded-Proto=https`；实际 HTTPS 请求无重定向循环，HTTP 公网入口跳到 HTTPS，登录响应的 Session/CSRF/刷新 Cookie 均按其用途携带 Secure 属性。`nginx -t` 在镜像内通过。

这些是待执行的实机验收项；静态配置不能证明网络隔离、代理传头或数据库权限。Railway Bucket、生产低权限数据库账号、多实例私有图片读写和恢复演练仍按缺陷表待验证。

## 本地验证命令

从仓库根目录：

```powershell
.venv\Scripts\python.exe backend\manage.py check
.venv\Scripts\python.exe backend\manage.py test apps.agent_api apps.core
npm --prefix frontend run build:check
```

数据库 backend、模型/测试命令入口见[数据库说明](database-current.md)与[文档索引](README.md)。
