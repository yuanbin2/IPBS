# Docker 部署指南

## 组件

Docker Compose 会启动：

- `frontend`：Vue 构建产物 + Nginx 统一入口，代理 API，并服务 media/static。
- `backend`：Django + DRF + Agent API。
- `postgres`：PostgreSQL + pgvector。
- `redis`：Celery result backend 与 Django 缓存。
- `rabbitmq`：Celery broker。
- `celery_worker`：异步任务 worker。
- `celery_beat`：定时任务调度。

## 首次部署

```bash
cp .env.example .env
```

修改 `.env`：

- `DJANGO_SECRET_KEY`
- `POSTGRES_PASSWORD`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `OPENAI_API_KEY` / `BAILIAN_API_KEY`
- `LANGSMITH_API_KEY`

启动：

```bash
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
docker compose logs -f backend
```

健康检查：

```bash
curl http://localhost/api/health/
```

## 管理员账号

```bash
docker compose exec backend python manage.py createsuperuser
```

登录前端 `/security`，或用 `POST /api/agent/auth/login/` 获取 token。

## 常用命令

```bash
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py test apps.agent_api
docker compose exec celery_worker celery -A config inspect ping
docker compose down
docker compose down -v
```

## 无 Docker 本地运行

Windows 双击项目根目录的 `start.bat`；Linux/macOS 执行：

```bash
chmod +x start.sh
./start.sh
```

本地模式使用 SQLite、进程内缓存和 Celery eager 模式，不依赖外部基础
设施。该模式会先构建 Vue，再由 Django 在 `http://127.0.0.1:8000/`
同时提供 SPA 和 API。

## 安全默认值

- `AGENT_SECURITY_ENFORCED=true`
- `.env` 不进入镜像，也不提交 Git。
- Nginx 设置基础安全响应头。
- Django 通过 `DJANGO_ALLOWED_HOSTS` 和 `DJANGO_CSRF_TRUSTED_ORIGINS` 配置部署域名。
- 审批、MCP 工具、安全状态、审计事件需要 RBAC 权限。

## CI/CD

GitHub Actions 位于 `.github/workflows/ci.yml`：

- 后端测试：`python manage.py test apps.agent_api apps.core`
- 前端构建：`npm run build`
- Compose 校验并构建前后端镜像。
