# 简历项目包装

## 项目名称

企业知识智能体平台 + 个人博客智能体系统

## 一句话介绍

从 0 到 1 搭建一个可部署、可观测、带权限安全和 Human-in-the-loop 的企业级 Agentic RAG 平台，并把个人博客内容接入为可问答的知识源。

## 简历写法

### 版本 A：偏 Agent 工程

企业知识智能体平台 | Vue 3 / Django / LangGraph / RAG / MCP / Docker

- 设计并实现多智能体知识平台，包含 RAG Agent、Blog Agent、MCP Tool Agent、SQL Analysis Agent、Review Agent、Admin Approval Agent，由 Supervisor 按问题类型路由。
- 构建 Agentic RAG 流程，支持文档上传、切片、embedding、检索、引用来源、回答生成和检索失败兜底。
- 将个人博客文章发布流程与知识库联动，文章发布后自动进入知识库，访客可通过博客智能体询问项目经历、技术栈和架构设计。
- 实现 Human-in-the-loop 审批机制，对删除文档、发布博客、MCP 工具调用等敏感操作进行人工审批并记录结果。
- 接入 MCP 工具注册表，支持工具启用/禁用、审批开关、权限范围和执行记录。
- 建立可观测与评估体系，记录 Agent trace、latency、tool success rate，并维护 30 条评估集覆盖博客、知识库、复杂问题和越权攻击。
- 完成 RBAC、workspace 隔离、安全审计、prompt injection 拦截和输出脱敏。
- 使用 Docker Compose 编排 Nginx、Vue、Django、PostgreSQL、Redis、Celery，并用 GitHub Actions 跑测试、构建和 Compose 校验。

### 版本 B：偏全栈工程

企业知识智能体平台 | Vue 3 / TypeScript / Django REST Framework / PostgreSQL / Docker

- 独立完成前后端 Monorepo，从基础架构、用户界面、API、数据库模型到部署流程完整落地。
- 前端实现博客、知识库、Agent 对话、审批后台、MCP 工具管理、观测评估、安全中心等工作台页面。
- 后端使用 Django REST Framework 设计文章、知识库、文档、审批、工具、观测、评估、权限等 API。
- 实现 Markdown 博客编辑与图片上传，支持文章发布审批、评论、归档、标签分类和知识库同步。
- 构建登录注册、token 自动携带、路由守卫和统一 AppShell 布局，提升系统完整性。
- 使用自动化测试覆盖 37 个关键后端场景，并通过前端类型检查和生产构建。

## 面试讲解顺序

1. 先讲业务目标：普通 RAG 项目升级为企业可控 Agent 平台。
2. 再讲架构：Vue 工作台、Django API、多智能体、知识库、审批、安全、部署。
3. 重点讲 Agent：Supervisor 路由、RAG 检索、MCP 工具、HITL 审批。
4. 讲工程质量：测试、CI、Docker、可观测、评估集。
5. 最后讲安全边界：RBAC、workspace、prompt injection、防密钥泄漏。

## 可量化成果

- 37 个后端自动化测试。
- 30 条 Agent 评估题。
- 8 个前端核心工作台页面。
- 7 个 Docker Compose 服务。
- 6 类 specialized agents。
- 4 类 MCP 工具。
