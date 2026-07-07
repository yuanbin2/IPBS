# Enterprise Knowledge Agent Platform with Personal Blog Agent

企业知识智能体平台 + 个人博客智能体系统。

这个仓库是一个企业级 Agent 工程化学习项目。第一阶段目标是搭建可启动的 monorepo，并逐步完成个人博客、企业知识库、Agentic RAG、多智能体协作、Human-in-the-loop、MCP 工具接入、可观测性和 CI/CD。

## 架构

```text
frontend/  Vue 3 + Vite + TypeScript + Pinia + Element Plus
backend/   Django + Django REST Framework + ASGI
agent/     LangChain + LangGraph agent workflows
docs/      架构文档、学习笔记、博客草稿
deploy/    Docker Compose、Nginx、部署配置
```

## 技术栈

| 层级 | 技术 | 负责能力 |
| --- | --- | --- |
| 前端 | Vue 3, Vite, TypeScript, Pinia, Element Plus | 博客、管理台、聊天页、文档上传、流式输出 |
| 后端 | Django, DRF, ASGI | 用户、权限、文章、知识库、Agent API |
| 异步任务 | Celery, Redis | 文档解析、向量化、知识库重建、长任务 |
| 数据库 | PostgreSQL, pgvector | 用户、文章、文档、向量、对话记录 |
| Agent | LangChain, LangGraph | Agent loop、tools、state graph、HITL |
| RAG | splitter, embedding, pgvector | 切分、检索、重排、引用来源 |
| 工具协议 | MCP | 搜索、GitHub、文件、数据库工具接入 |
| 可观测 | LangSmith | trace、debug、评估、成本与延迟分析 |
| 工程质量 | pytest, pre-commit, GitHub Actions | 单测、接口测试、CI 检查 |

## 本地启动

### 1. 启动基础设施

```bash
docker compose up -d postgres redis
```

### 2. 启动后端

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
copy ..\.env.example ..\.env
python manage.py migrate
python manage.py runserver
```

后端健康检查：`http://127.0.0.1:8000/api/health/`

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端地址：`http://127.0.0.1:5173/`

## 第 1 天完成项

- 初始化 monorepo：`frontend/`、`backend/`、`agent/`、`docs/`、`deploy/`
- 创建 Django + DRF + ASGI 后端工程
- 配置 PostgreSQL、Redis、环境变量、日志
- 创建 Vue3 + Vite + TypeScript 前端工程
- 接入 Pinia、Vue Router、Element Plus
- 添加 Docker Compose 和 Nginx 配置草稿
- 写清项目目标、架构图、技术栈和第一篇博客草稿

## 第 2 天完成项

- 在 `agent/` 中实现最小 Agent tool-calling loop
- 实现博客检索、当前用户资料、简单计算器 3 个工具
- 后端新增 `POST /api/agent/chat/`
- 前端新增 `/chat` Agent 聊天页面
- 支持展示工具调用名称、输入、输出
