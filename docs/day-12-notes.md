# 第 12 天：权限、安全与工程化

## 目标

把 Agent 项目从“功能可用”推进到“有企业安全边界”：登录、RBAC、workspace 隔离、工具权限、敏感输入拦截、输出脱敏、审计记录和环境变量治理。

## 已完成能力

### 登录与身份

- 新增 `POST /api/agent/auth/login/`。
- 支持 Django Session 登录。
- 登录成功后返回服务端签名 token，可通过 `Authorization: Bearer <token>` 调用接口。
- 新增 `GET /api/agent/auth/me/` 查看当前身份。

### RBAC

新增 `UserProfile`：

- `admin`：审批、删除、MCP 工具管理、安全状态、安全审计。
- `operator`：上传文档、写博客、运行评估、查看观测、执行已启用工具。
- `visitor`：公开博客、博客 Agent、普通对话。

通过环境变量控制强制鉴权：

```env
AGENT_SECURITY_ENFORCED=true
```

开发环境默认关闭强制鉴权，避免影响本地调试；测试中会开启验证。

### Workspace / Tenant

新增 `workspace_key` 字段：

- Conversation
- AgentRun
- KnowledgeBase
- Document
- BlogArticle
- ApprovalRequest
- MCPTool
- AgentObservation
- EvaluationCase
- EvaluationRun
- UserProfile
- SecurityAuditEvent

接口按 `X-Workspace` 或登录用户 profile 中的 workspace 过滤数据，降低跨知识库、跨空间读取风险。

### Agent 安全

- Prompt injection / 越权输入检测：
  - API Key
  - secret / password
  - 数据库结构
  - 忽略规则
  - 绕过审批
  - 删除所有
  - drop table
- 命中后转交 `Admin Approval Agent`，不直接执行。
- 输出脱敏会替换疑似 token、API Key、password、secret。
- 敏感输入、拒绝访问、输出脱敏会写入 `SecurityAuditEvent`。

### 工具安全

- MCP 工具仍通过注册表启用/禁用。
- 高风险工具可设置 `requires_approval`。
- SQL 分析 Agent 只返回聚合统计，不暴露表结构和字段。
- 审批执行时按审批单 workspace 再次查对象，避免 payload 越权。

### 运维安全

新增：

- `GET /api/agent/security/status/`
- `GET /api/agent/security/audit-events/`

安全状态只返回检查结果，不返回密钥值：

- `.env` 是否存在
- `.env` 是否被 Git 跟踪
- 是否开启强制鉴权
- DEBUG 状态
- ALLOWED_HOSTS
- LangSmith 是否配置

## 前端

新增 `/security` 页面：

- 登录表单
- 当前身份和 workspace
- 安全检查
- 安全审计事件

## 测试策略

第 9-12 天后续都要做完整回归：

- 后端 Django test 全量跑通。
- 前端 `npm run build` 跑通。
- 覆盖人工审批、MCP 工具、可观测性/评估集、安全权限。
- 新增安全测试会显式开启 `AGENT_SECURITY_ENFORCED=True`，验证权限拦截是真实生效。
