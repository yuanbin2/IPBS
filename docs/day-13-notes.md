# 第 13 天：Docker 部署 + CI/CD

## 目标

让项目像企业项目一样可以部署、可复现、可测试。

## 部署组件

Docker Compose 包含：

- `nginx`
- `frontend`
- `backend`
- `postgres`
- `redis`
- `celery_worker`
- `celery_beat`

## 新增文件

- `backend/Dockerfile`
- `frontend/Dockerfile`
- `deploy/backend/entrypoint.sh`
- `deploy/nginx/default.conf`
- `.dockerignore`
- `.github/workflows/ci.yml`
- `docs/deployment.md`
- `docs/api.md`
- `docs/system-architecture.md`

## 一条命令启动

```bash
cp .env.example .env
docker compose up -d --build
```

Windows PowerShell：

```powershell
copy .env.example .env
docker compose up -d --build
```

## CI

GitHub Actions 做三类检查：

- 后端测试：Django tests
- 前端构建：Vue type check + Vite build
- Compose 校验：`docker compose config`

## 第 12 天安全补充

- `.env.example` 改为部署安全默认值。
- `AGENT_SECURITY_ENFORCED=true` 作为容器默认。
- Nginx 增加安全响应头。
- Django 增加 `DJANGO_CSRF_TRUSTED_ORIGINS` 和反向代理 HTTPS 识别。
- Docker 镜像通过 `.dockerignore` 排除 `.env`、虚拟环境、node_modules、media、staticfiles。

## 验收

本地已执行：

- 后端完整测试
- 前端生产构建
- Docker Compose 配置校验

如果本机可以访问 Docker Hub / npm / PyPI，可以继续执行：

```bash
docker compose up -d --build
curl http://localhost/api/health/
```
