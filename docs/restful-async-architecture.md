# RESTful、异步任务与 JWT 架构说明

## API 设计

服务端使用 Django REST Framework，以资源为中心提供 JSON API：

- `/api/agent/auth/*`：注册、登录、刷新令牌和当前用户。
- `/api/agent/blog/articles/*`：文章集合与单篇文章资源。
- `/api/agent/knowledge-bases/*`：知识库资源。
- `/api/agent/documents/*`：文档上传、查询、删除和重建。
- `/api/agent/tasks/{task_id}/`：异步任务状态资源。

接口使用 HTTP 方法表达动作（GET、POST、PATCH、DELETE），使用 HTTP 状态码表达结果。耗时操作返回
`202 Accepted`，响应中的 `task_url` 用于轮询；资源创建使用 `201 Created`，普通查询和更新使用 `200 OK`。

## 为什么采用异步编程

文档解析、PDF 读取、文本切片、远程 Embedding 和批量重建可能持续数秒甚至数分钟。如果在 Web
请求进程中执行，会占住 worker、造成超时并降低并发能力。因此上传和重建只负责持久化文件并投递任务，
Celery worker 在后台执行真正的索引工作。前端的网络请求、JWT 刷新和任务轮询采用
`async/await`，避免阻塞浏览器 UI。

普通数据库 CRUD 很短，继续同步执行更简单；异步不是目的，只用于 I/O 密集、耗时或需要重试的边界。

## Celery、RabbitMQ 与 Redis 的职责

- **Celery**：后台任务执行框架，提供 worker、失败重试、状态跟踪和独立扩容能力。
- **RabbitMQ**：Celery broker。它负责可靠传递任务消息、确认（ack）、路由和积压削峰。与缓存分离后，
  Redis 故障或缓存淘汰不会直接丢失待执行任务。
- **Redis**：Celery result backend 和 Django cache。任务状态适合短期快速读取，缓存也需要低延迟；
  它不承担本项目的可靠任务队列职责。

文档任务启用 late ack、worker 丢失时重新入队、指数退避重试和独立 `documents` 队列。任务应保持幂等：
重复执行时先重建该文档的切片和向量，不追加重复索引。

## JWT 安全机制

登录成功返回短期 access token（默认 15 分钟）和长期 refresh token（默认 7 天）。客户端通过
`Authorization: Bearer <access>` 调用 API；access 过期时使用 refresh token 获取新令牌。

JWT 只证明身份，授权仍由 RBAC 和 workspace 隔离完成。生产环境必须使用高强度
`DJANGO_SECRET_KEY`、HTTPS，并缩短 access token 生命周期。浏览器当前使用 localStorage 以兼容现有
SPA；面向公网时更推荐把 refresh token 放入 `Secure + HttpOnly + SameSite` Cookie，并启用 refresh
token 黑名单/撤销，以降低 XSS 窃取令牌的风险。

## 启动

```bash
copy .env.example .env
docker compose up -d --build
```

RabbitMQ 管理界面默认位于 `http://localhost:15672`。部署前必须修改 RabbitMQ、PostgreSQL 和 Django
密钥，不能使用示例密码。
