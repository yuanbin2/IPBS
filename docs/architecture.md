# 架构草图

```text
User
  |
  v
Vue 3 Frontend
  |
  v
Django REST API ---- Redis/Celery Worker
  |                       |
  v                       v
PostgreSQL + pgvector   Document Parsing / Embedding
  |
  v
LangGraph Agent Runtime
  |
  +-- RAG Retriever
  +-- MCP Tools
  +-- HITL Approval
  +-- LangSmith Trace
```

## 第一天边界

今天只建立可启动工程底座，不实现完整 Agent 业务逻辑。核心验证点是：

- 后端服务可以启动并返回健康检查
- 前端服务可以启动并展示项目概览
- PostgreSQL 和 Redis 可以通过 Docker Compose 启动
- README 能解释项目定位、目录结构和技术栈

