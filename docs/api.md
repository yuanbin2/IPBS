# API 文档

默认前缀：`/api/agent/`

## Auth

- `POST /auth/login/`：用户名密码登录，返回 signed token。
- `GET /auth/me/`：查看当前 actor、role、workspace。

## Chat / Agent

- `POST /chat/`：Agent 对话。
- `GET /conversations/`：会话列表。
- `GET /conversations/<id>/`：会话详情。

## Knowledge

- `GET /knowledge-bases/`
- `POST /knowledge-bases/`
- `DELETE /knowledge-bases/<id>/`
- `GET /documents/`
- `POST /documents/`
- `DELETE /documents/<id>/`
- `POST /documents/<id>/reindex/`
- `POST /knowledge-search/`

## Blog

- `GET /blog/articles/`
- `POST /blog/articles/`
- `GET /blog/articles/<slug>/`
- `PATCH /blog/articles/<slug>/`
- `DELETE /blog/articles/<slug>/`
- `POST /blog/articles/<slug>/publish/`
- `POST /blog/images/`
- `GET /blog/categories/`
- `GET /blog/tags/`
- `GET /blog/archive/`
- `GET /blog/about/`
- `POST /blog/agent/chat/`

## Human-in-the-loop

- `GET /approvals/`
- `POST /approvals/<id>/`

敏感操作会先创建审批单：

- 删除文档
- 删除知识库
- 删除博客
- 发布博客
- 需要审批的 MCP 工具调用

## MCP Tools

- `GET /mcp-tools/`
- `PATCH /mcp-tools/<id>/`
- `POST /mcp-tools/<id>/execute/`

默认工具：

- `local_file_search`
- `git_repo_info`
- `web_search`
- `safe_database_stats`

## Observability / Evaluation

- `GET /observability/`
- `GET /evaluation-cases/`
- `POST /evaluation-runs/`

指标：

- `answer_correctness`
- `faithfulness`
- `citation_accuracy`
- `latency_ms`
- `tool_success_rate`

## Security

- `GET /security/status/`
- `GET /security/audit-events/`

生产建议：

- 使用 `Authorization: Bearer <token>`。
- 设置 `AGENT_SECURITY_ENFORCED=true`。
- 管理类接口需要 `operator` 或 `admin`。
- `X-Workspace` 可用于开发环境切换 workspace，生产以用户 profile 为准。
