# 从 RAG Demo 到企业级 Agent 平台：14 天工程化实践复盘

过去 14 天，我围绕“企业知识智能体平台 + 个人博客智能体系统”做了一次完整的 Agent 工程化实践。

这个项目一开始只是一个普通的知识库问答系统，但最终目标不是停留在“能回答问题”，而是做到可发布、可审批、可观测、可评估、可部署。

## 为什么不是普通 RAG Demo

普通 RAG 项目通常只包含：

- 上传文档
- 向量化
- 检索
- 调用大模型回答

但真实企业项目里，问题远不止这些。

比如：

- 删除文档能不能直接执行？
- 发布博客是否需要审核？
- 工具调用是否会泄漏数据？
- Agent 回答有没有引用来源？
- 运行失败如何排查？
- 如何证明效果真的变好了？
- 如何部署到服务器？

所以这个项目从第 6 天开始，把个人博客、知识库、Agent、审批、安全、观测和部署全部串起来。

## 核心架构

项目采用 monorepo：

- `frontend`：Vue 3 + TypeScript + Element Plus
- `backend`：Django + Django REST Framework
- `agent`：LangGraph / LangChain 风格 Agent 工作流
- `docs`：架构、部署、API、演示和复盘文档
- `deploy`：Nginx、Docker、部署脚本

系统入口是一个统一工作台：

- 博客
- 知识库
- Agent 对话
- 人工审批
- MCP 工具
- 观测评估
- 安全中心

## 多智能体设计

我设计了一个 Supervisor Agent，用来根据用户问题路由到不同 specialized agents：

- `RAG Agent`：知识库问答
- `Blog Agent`：博客和个人经历问答
- `MCP Tool Agent`：外部工具调用
- `SQL Analysis Agent`：安全聚合统计
- `Writing Agent`：写作和总结
- `Review Agent`：回答质量审查
- `Admin Approval Agent`：敏感操作审批

这让系统不再是一个所有问题都塞给 RAG 的简单机器人，而是一个有职责边界的 Agent 平台。

## Human-in-the-loop

真实企业环境里，Agent 不能黑盒自动执行高风险动作。

所以我实现了 HITL 审批：

- 删除知识库
- 删除文档
- 发布博客
- 删除博客
- MCP 工具调用

这些动作会先创建审批单，管理员批准后才执行。审批结果会被记录，失败也会保留原因。

## MCP 工具接入

项目内置了 MCP 工具注册表：

- 本地文件搜索
- Git 仓库信息
- 网页搜索占位
- 安全数据库统计

每个工具都有：

- 启用状态
- 权限范围
- 是否需要审批
- 最后调用时间

如果工具设置为“需审批”，前端会弹出审批窗口，管理员批准后才执行。

## 可观测性与评估集

为了不只凭感觉判断效果，我做了本地观测和评估体系。

每次 Agent 运行都会记录：

- 输入
- 回答
- selected agent
- trace
- tool calls
- sources
- latency
- tool success rate
- failure reason

同时内置 30 条评估题，覆盖：

- 博客类
- 知识库类
- 复杂问题
- 越权攻击

评估指标包括：

- answer correctness
- faithfulness
- citation accuracy
- latency
- tool success rate

## 安全边界

第 12 天重点补了安全：

- 登录注册
- signed token
- RBAC
- workspace 隔离
- prompt injection 拦截
- 输出脱敏
- 安全审计
- `.env` 不入 Git

这一步让项目从“能跑”更接近“能上线”。

## Docker 与 CI/CD

最后我补了完整部署：

- Nginx
- Frontend
- Backend
- PostgreSQL + pgvector
- Redis
- Celery Worker
- Celery Beat

并加入 GitHub Actions：

- 后端测试
- 前端构建
- Docker Compose 校验

## 项目收获

这个项目最重要的收获是：Agent 工程化不是只会调模型 API。

真正有价值的部分在于：

- 能不能把业务数据接进去？
- 能不能解释回答来源？
- 能不能控制工具权限？
- 能不能审批高风险动作？
- 能不能观测和评估？
- 能不能部署和持续测试？

这也是我希望这个项目在面试中展示出的能力：不是只写一个聊天框，而是能把 Agent 项目做成一个完整系统。

## 下一步

后续可以继续增强：

- 接入真实 LangSmith trace。
- MCP 外部工具接入 GitHub / Web Search。
- 使用真实只读 SQL 用户。
- 增加 Playwright e2e 测试。
- 引入对象级权限和团队空间管理。

这个项目到这里已经可以作为一个完整的 Agent 工程化作品集项目。
