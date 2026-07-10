# 演示视频脚本

建议录 5 个短视频，每个 3-5 分钟。录制时只展示功能和关键代码，不需要从头解释所有背景。

## 视频 1：项目总览与登录

目标：证明这是一个完整平台，不是零散 demo。

操作路线：

1. 打开 `/login`。
2. 注册或登录管理员账号。
3. 进入首页，展示统一侧边栏：博客、知识库、对话、审批、MCP、观测、安全。
4. 打开 `/security`，展示当前 actor、role、workspace、安全检查和审计事件。

讲解词：

> 这个项目是企业知识智能体平台。它不是单点 RAG demo，而是把博客内容、知识库、Agent、人工审批、安全和部署都串起来。登录后进入统一工作台，所有管理能力都受 RBAC 和 workspace 控制。

## 视频 2：上传文档到知识库

目标：证明知识库链路跑通。

操作路线：

1. 进入 `/knowledge`。
2. 创建或选择知识库。
3. 上传 Markdown / txt / PDF。
4. 查看文档状态、切片数量。
5. 在搜索框输入相关问题，展示检索结果和 score。

讲解词：

> 文档上传后会进入知识库，后端进行文本抽取、切片和 embedding。搜索时返回相关 chunk，并保留 document、chunk、score 等信息，后续 Agent 回答会基于这些来源生成引用。

## 视频 3：Agent 问答与引用

目标：证明 Agentic RAG 和多智能体路由。

操作路线：

1. 进入 `/chat`。
2. 提问：“请根据知识库解释 Agentic RAG 是什么？”
3. 展示回答、sources、tool calls、trace。
4. 再提问：“统计当前有多少文章和文档。”
5. 展示 Supervisor 切到 SQL Analysis Agent。

讲解词：

> 对话入口由 Multi-Agent Supervisor 先判断问题类型，再交给 RAG Agent、SQL Analysis Agent、Blog Agent 或 MCP Tool Agent。页面会展示 trace、工具调用和引用来源，方便定位 Agent 是怎么做出回答的。

## 视频 4：MCP 工具 + 人工审批

目标：证明工具权限和 HITL。

操作路线：

1. 进入 `/mcp-tools`。
2. 打开某个工具的“需审批”。
3. 点击“申请审批调用”。
4. 在弹窗中点击“批准并执行”。
5. 展示执行结果和审批状态。
6. 进入 `/admin-approvals` 查看审批记录。

讲解词：

> MCP 工具不是黑盒自动执行。工具有启用状态、权限范围和是否需要审批。高风险调用会先创建审批单，管理员批准后才执行，并且审批结果会被记录下来。

## 视频 5：可观测性、评估与部署

目标：证明项目可运维、可持续优化。

操作路线：

1. 进入 `/observability`。
2. 展示运行次数、成功率、平均耗时、工具成功率。
3. 展示评估集：博客、知识库、复杂问题、越权攻击。
4. 跑一条评估。
5. 打开 `docs/deployment.md` 和 `docker-compose.yml`。

讲解词：

> 企业项目不能只说“效果不错”，要能记录、评估和持续优化。这里每次 Agent 运行都会记录 observation，评估集用于验证正确性、faithfulness、citation accuracy、latency 和 tool success rate。部署层用 Docker Compose 编排 Nginx、前端、后端、PostgreSQL、Redis 和 Celery。

## 截图清单

- 登录页
- 首页工作台
- 知识库上传和搜索
- Agent 对话 trace / sources
- MCP 审批弹窗
- 人工审批后台
- 观测评估页面
- 安全中心
- Docker Compose 文件
- GitHub Actions CI 文件
