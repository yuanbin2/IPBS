# 项目结构

本项目参考 AIFriends 的“按业务模块拆分视图和前端请求层”思路，但 API 保持资源式 REST
设计，不采用 `create/delete/get_single` 等动作式路径。

```text
backend/
  config/                       Django、ASGI、Celery 配置
  apps/
    core/                       健康检查等平台基础能力
    users/                      用户域
    agent_api/
      api_urls/                 按业务域组织的 URL
        auth.py                 JWT、当前用户、安全审计
        agent.py                对话、Agent、评估、可观测性
        knowledge.py            知识库、文档、搜索、任务状态
        governance.py           审批和 MCP 工具
        blog.py                 文章、评论、博客 Agent
      views/                    与 URL 对应的 DRF View 模块
      serializers/              按业务域组织的 DRF Serializer
      services/                 RAG、博客发布、博客 Agent 等业务服务
      tasks.py                  Celery 异步任务
      models/                   按领域拆分的持久化模型

frontend/src/
  api/client.ts                 JWT 注入、刷新去重和失败重试
  stores/                       会话与页面状态
  router/                       页面路由与访问控制
  views/                        页面级组件
  components/                   复用 UI
```

## 分层约束

- `api_urls` 只声明 URL，不放业务逻辑。
- `views` 负责参数校验、权限检查、调用领域服务和构造 HTTP 响应。
- `serializers` 负责模型输出、嵌套关系和 API 数据表示。
- `tasks` 只承载可重试、耗时的后台工作。
- `rag.py`、`blog.py` 等领域服务不依赖 HTTP request，可由 API、Celery 或测试复用。
- 前端页面不自行实现 JWT 刷新，统一经过 `api/client.ts`。

## REST 约定

- 集合：`GET/POST /resources/`
- 单资源：`GET/PATCH/DELETE /resources/{id}/`
- 耗时工作：返回 `202 Accepted` 和任务资源地址
- 认证：`Authorization: Bearer <access-token>`
- 错误：使用恰当的 4xx/5xx 状态码并返回 `detail`

各领域 View 直接定义在对应模块中，不经过兼容转发层。跨领域复用的序列化、权限与审计辅助函数
集中在 `views/common.py`；可复用业务逻辑应继续下沉到领域服务，而不是堆积在 View 中。
