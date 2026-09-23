# 企业知识智能体平台 — 系统知识库

> 本文档记录整个系统的架构、模块、API、数据模型等关键信息，供后续维护和升级参考。

---

## 一、项目概述

**项目名称：** Knowledge Agent（企业知识智能体平台）

**核心功能：** 一个个人知识 + 博客平台，博客文章发布后自动向量化进入知识库，访客可通过 AI Agent 检索文章内容。

**技术栈：**

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + TypeScript + Vite + Element Plus + md-editor-v3 |
| 后端 | Django 5 + Django REST Framework + SimpleJWT |
| 数据库 | PostgreSQL 16（pgvector）/ SQLite（本地开发） |
| 缓存 | Redis 7 / LocMem（本地） |
| 任务队列 | Celery + RabbitMQ + Redis |
| AI/LLM | LangChain + LangGraph + OpenAI 兼容 API |
| 向量存储 | pgvector（生产）/ Django JSON（开发） |
| 部署 | Docker Compose / Railway |

---

## 二、目录结构

```
Blog/
├── agent/                    # 独立 Python Agent 模块（LangGraph/LangChain）
│   ├── simple_agent.py       # 单 Agent RAG 实现
│   ├── multi_agent.py        # 多 Agent 编排
│   ├── mcp_tools.py          # MCP 工具集成
│   ├── security.py           # Agent 安全模块
│   └── tools.py              # 工具定义
├── backend/                  # Django 后端
│   ├── config/               # Django 配置（settings, urls, wsgi）
│   ├── apps/
│   │   ├── agent_api/        # 主应用（Agent、博客、知识库、RAG）
│   │   │   ├── models/       # 数据模型
│   │   │   ├── views/        # API 视图
│   │   │   ├── serializers/  # DRF 序列化器
│   │   │   ├── services/     # 业务逻辑层
│   │   │   ├── api_urls/     # URL 路由
│   │   │   └── migrations/   # 数据库迁移
│   │   ├── core/             # 健康检查、基础路由
│   │   └── users/            # 用户模型
│   └── media/                # 上传文件存储
├── frontend/                 # Vue 3 SPA
│   ├── src/
│   │   ├── api/              # API 客户端（fetch 拦截器）
│   │   ├── components/       # 共享组件（AppShell）
│   │   ├── features/         # 功能模块
│   │   │   ├── blog/         # 博客模块
│   │   │   ├── chat/         # 对话模块
│   │   │   └── knowledge/    # 知识库模块
│   │   ├── router/           # 路由配置
│   │   ├── stores/           # Pinia 状态管理
│   │   └── views/            # 页面视图
│   └── dist/                 # 构建产物
├── deploy/                   # 部署脚本
├── docker-compose.yml        # Docker 编排
├── Dockerfile                # 后端镜像
└── .env                      # 环境变量
```

---

## 三、数据模型

### 3.1 Agent 域

| 模型 | 说明 |
|------|------|
| `Conversation` | 多轮对话会话（workspace 隔离） |
| `Message` | 用户/Agent 消息（含 tool_calls, sources, trace） |
| `AgentRun` | 单次运行遥测 |

### 3.2 知识库域

| 模型 | 说明 |
|------|------|
| `KnowledgeBase` | 命名集合，workspace 隔离 |
| `Document` | 上传文档（PDF/文本），状态：pending→processing→ready/failed |
| `DocumentChunk` | 文本分块 |
| `EmbeddingRecord` | 向量嵌入（JSON 字段） |

### 3.3 博客域

| 模型 | 说明 |
|------|------|
| `ArticleCategory` | 文章分类（name, slug, description） |
| `ArticleTag` | 文章标签（name, slug） |
| `BlogArticle` | 博客文章（title, slug, author_name, summary, **cover_image**, content, category FK, tags M2M, status, view_count, knowledge_document FK, published_at） |
| `BlogComment` | 文章评论（article FK, author_name, content, is_approved） |
| `BlogAgentSession` | 博客 Agent 会话 |
| `BlogAgentMessage` | 博客 Agent 消息 |
| `BlogAgentSecurityEvent` | 安全事件 |

**文章状态流转：**
```
draft → (审批通过) → published
draft → (审批拒绝) → rejected
published → (编辑) → draft → (重新审批) → published
```

### 3.4 治理域

| 模型 | 说明 |
|------|------|
| `ApprovalRequest` | 人工审批队列（发布/删除博客、执行 MCP 工具） |
| `UserProfile` | 用户角色：admin, operator, visitor |
| `MCPTool` | MCP 工具配置 |
| `SecurityAuditEvent` | 安全审计事件 |

---

## 四、API 清单

### 4.1 博客 API（`/api/agent/blog/`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `articles/` | GET | 文章列表（支持 status, category, tag, q, author_name 筛选） |
| `articles/` | POST | 创建文章（需审批） |
| `articles/<slug>/` | GET | 文章详情（含内容和评论） |
| `articles/<slug>/` | PUT | 更新文章（普通用户） |
| `articles/<slug>/` | PATCH | 更新文章（管理员） |
| `articles/<slug>/` | DELETE | 删除文章（需审批） |
| `articles/<slug>/publish/` | POST | 触发发布审批 |
| **`articles/<slug>/related/`** | **GET** | **相关文章推荐** |
| `articles/<slug>/comments/` | GET | 文章评论列表 |
| `articles/<slug>/comments/` | POST | 发表评论 |
| `images/` | POST | 图片上传 |
| `categories/` | GET | 分类列表 |
| `tags/` | GET | 标签列表 |
| `archive/` | GET | 按月归档 |
| `about/` | GET | 关于信息 |
| `agent/chat/` | GET/POST | 博客 Agent 对话 |

### 4.2 Agent 对话 API（`/api/agent/`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `chat/` | POST | Agent 对话 |
| `chat/stream/` | POST | 流式对话 |
| `conversations/` | GET | 会话列表 |
| `conversations/<id>/` | GET | 会话详情 |

### 4.3 知识库 API（`/api/agent/`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `knowledge-bases/` | GET/POST | 知识库 CRUD |
| `documents/` | GET/POST | 文档 CRUD |
| `documents/<id>/ingest/` | POST | 触发文档向量化 |

### 4.4 认证 API（`/api/agent/auth/`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `login/` | POST | 登录（返回 JWT） |
| `register/` | POST | 注册 |
| `refresh/` | POST | 刷新 Token |
| `me/` | GET | 当前用户信息 |

### 4.5 治理 API（`/api/agent/`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `approvals/` | GET | 审批队列 |
| `approvals/<id>/` | POST | 审批操作 |
| `observability/` | GET | 观测指标 |
| `mcp-tools/` | GET/POST | MCP 工具管理 |
| `security/` | GET/POST | 安全配置 |

---

## 五、前端路由

| 路径 | 视图 | 说明 |
|------|------|------|
| `/landing` | LandingView | 公开着陆页 |
| `/login` | LoginView | 登录注册 |
| `/` | HomeView | 仪表盘 |
| `/blog/:slug?` | BlogView | 博客（列表/详情/编辑） |
| `/chat` | AgentChatView | Agent 对话 |
| `/knowledge` | KnowledgeBaseView | 知识库管理 |
| `/admin-approvals` | AdminApprovalView | 审批队列（管理员） |
| `/mcp-tools` | MCPToolsView | MCP 工具管理 |
| `/observability` | ObservabilityView | 观测评估 |

---

## 六、前端组件树

```
App.vue
├── AppShell.vue（侧边栏导航）
│   ├── 概览 → HomeView
│   ├── 博客 → BlogView
│   │   ├── BlogWriter（Markdown 编辑器 + 封面图上传）
│   │   ├── ArticleList（文章卡片列表 + 分类筛选chips）
│   │   ├── ArticleDetail（文章详情 + 封面图 + 相关推荐 + 评论）
│   │   ├── BlogSidebar（标签云 + 分类列表 + 归档 + 关于）
│   │   └── BlogAgentWidget（浮动 Agent 对话）
│   ├── 知识库 → KnowledgeBaseView
│   │   ├── DocumentManager
│   │   ├── KnowledgeBaseSidebar
│   │   └── KnowledgeSearchPanel
│   ├── 对话 → AgentChatView
│   │   ├── ChatComposer
│   │   ├── ChatMessageList
│   │   └── ConversationSidebar
│   ├── MCP 工具 → MCPToolsView
│   ├── 观测评估 → ObservabilityView
│   └── 审批 → AdminApprovalView
├── LandingView（公开）
└── LoginView（公开）
```

---

## 七、核心业务流程

### 7.1 博客发布流程

```
用户撰写文章 → 点击发布
    ↓
创建 BlogArticle（status=draft）
创建 ApprovalRequest（action=PUBLISH_BLOG_ARTICLE）
    ↓
管理员审批通过
    ↓
execute_approval_request()
  → publish_article_to_knowledge_base()
    → 创建/更新 Document
    → ingest_document()（分块 + 向量化）
    → 设置 status=published, published_at
```

### 7.2 RAG 检索流程

```
用户提问 → AgentChatView.post()
    ↓
MultiAgentSupervisor.route()
    ↓
simple_agent.py: retrieve node
    → search_knowledge_base()
      → 向量相似度（pgvector cosine, 权重 0.72）
      → 关键词/BM25（权重 0.28）
      → 双语查询别名（中英文技术术语）
    ↓
grade node → 判断文档相关性
    ↓
generate node → LLM 生成回答（含来源引用）
```

### 7.3 相关文章推荐算法

```
输入：当前文章 A
候选：所有已发布文章（排除 A）

对每篇候选文章计算得分：
  - 同分类: +10 分
  - 每个共同标签: +3 分
  - 浏览量对数归一化: +0~5 分

按得分降序排列，返回前 6 篇
```

---

## 八、设计系统

### 8.1 色彩体系

| 用途 | 色值 |
|------|------|
| 主色 | `#276678`（深海蓝绿） |
| 强调色 | `#b86f43`（铜色） |
| 成功 | `#2f7d5c` |
| 警告 | `#b7791f` |
| 危险 | `#b64b4b` |
| 信息 | `#3f6fa8` |
| 背景 | `#f4f6f7` |
| 表面 | `#ffffff` |
| 侧边栏 | `#17262e` |

### 8.2 字体

```
Inter, "PingFang SC", "Microsoft YaHei", "Noto Sans SC", Arial, sans-serif
```

### 8.3 间距系统（4px 基准）

`--space-1: 4px` → `--space-12: 48px`

---

## 九、环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `BLOG_LOCAL_MODE` | 本地开发模式（SQLite） | `false` |
| `DJANGO_SECRET_KEY` | Django 密钥 | 必填 |
| `DJANGO_DEBUG` | 调试模式 | `true` |
| `OPENAI_API_KEY` | LLM API 密钥 | - |
| `OPENAI_BASE_URL` | LLM API 地址 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `OPENAI_MODEL` | LLM 模型 | `qwen-plus` |
| `EMBEDDING_MODEL` | 嵌入模型 | `text-embedding-v1` |
| `EMBEDDING_DIMENSIONS` | 嵌入维度 | `384` |
| `DATABASE_URL` | 数据库连接串 | SQLite |
| `REDIS_URL` | Redis 地址 | LocMem |
| `CELERY_BROKER_URL` | RabbitMQ 地址 | - |
| `LANGSMITH_API_KEY` | LangSmith 追踪 | - |
| `AGENT_SECURITY_ENFORCED` | 启用安全检查 | `false` |
| `VITE_API_BASE_URL` | 前端 API 基础地址 | `""` |

---

## 十、部署架构

### Docker Compose 服务

| 服务 | 镜像 | 用途 |
|------|------|------|
| frontend | Node 20 → nginx:1.27 | SPA + 反向代理 |
| backend | Python 3.10 + Django | API（Gunicorn） |
| celery_worker | 同 backend | 异步任务 |
| celery_beat | 同 backend | 定时任务 |
| postgres | pgvector:pg16 | 数据库 |
| redis | redis:7 | 缓存 + Celery 结果 |
| rabbitmq | rabbitmq:3.13 | 消息队列 |

### Nginx 配置

- `/api/` 和 `/admin/` → proxy_pass backend:8000
- SPA 路由：`try_files $uri $uri/ /index.html`
- 静态资源缓存：assets 30天，media 7天

---

## 十一、开发规范

### 命名约定

- Python：snake_case（函数/变量）、PascalCase（类）
- TypeScript：camelCase（函数/变量）、PascalCase（组件/接口）
- CSS：kebab-case（类名），使用 CSS 自定义属性
- URL：kebab-case

### Git 提交规范

```
feat: 新功能
fix: 修复
docs: 文档
style: 样式
refactor: 重构
test: 测试
chore: 构建/工具
```

### 文件组织

- 后端：按功能分层（models → services → views → serializers → urls）
- 前端：按功能模块（features/blog/ → components/ + types.ts + utils/）

---

## 十二、变更日志

### 2026-09-23 博客模块增强

**新增功能：**
1. 文章封面图（`cover_image` 字段）
2. 相关文章推荐（`/articles/<slug>/related/`）
3. 分类筛选chips
4. 文章卡片重设计（左图右文布局）
5. 侧边栏分类增强
6. 编辑器封面图上传

**修改文件：**
- 后端：models, serializers, services, views, api_urls, migration
- 前端：types, ArticleList, ArticleDetail, BlogWriter, BlogSidebar, BlogView, style.css

**向后兼容：** 所有现有功能（审批、知识库同步、Agent对话、评论）不受影响。