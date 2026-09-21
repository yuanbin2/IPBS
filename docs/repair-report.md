# 项目修复与验证报告

修复日期：2026-07-27

## 已修复问题

1. 统一 Vite 构建目录为 `frontend/dist`，修复前端 Dockerfile 复制不存在的
   `/app/dist` 导致镜像构建失败的问题。
2. 统一开发环境、Django SPA fallback 与 Nginx 的 `/assets/` 静态资源路径。
3. 简化 Docker 入口：`frontend` 镜像直接作为 Vue/Nginx 网关，移除重复的
   Nginx 容器和容易失效的前端共享卷初始化流程。
4. 增加 `BLOG_LOCAL_MODE`。本机运行时自动使用 SQLite、LocMem Cache 和
   Celery eager 模式，不再强制要求 PostgreSQL、Redis、RabbitMQ。
5. 修复本地 Celery eager 模式下文档上传仍轮询 Redis 任务结果的问题。
6. 增加 SOCKS 代理依赖，并固定已验证的 Python 直接依赖版本。
7. 修正 `MEDIA_URL`，避免在多级前端路由中生成错误的相对媒体地址。
8. 前端尚未构建时，Django 返回带解决办法的 503 JSON，不再抛出模板 500。
9. 增加 Windows `start.bat` 与 Linux/macOS `start.sh` 一键启动脚本。
10. 更新 Docker、CI、本地启动和基础设施说明。

## 验证结果

- Django system check：通过。
- Django migration drift check：通过，无未生成迁移。
- 后端自动化测试：60/60 通过。
- Python 依赖一致性：通过。
- Vue TypeScript 检查与 Vite production build：通过。
- npm 依赖树：通过。
- Docker Compose YAML 结构与关键服务关系：通过。
- 本机真实 HTTP 冒烟测试：SPA 首页、JS 资源、健康检查、注册、JWT 身份
  校验和博客列表接口全部返回成功。

## 启动方式

Windows 双击项目根目录的 `start.bat`。Linux/macOS 执行：

```bash
chmod +x start.sh
./start.sh
```

启动后访问 `http://127.0.0.1:8000/`。

Docker 部署执行：

```bash
cp .env.example .env
docker compose up -d --build
```

发布前必须修改 `.env` 中的 Django、PostgreSQL 和 RabbitMQ 密钥。模型 Key
是可选项；不配置时项目会使用本地检索与降级回答路径。
