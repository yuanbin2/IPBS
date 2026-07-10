# Day 8: 多智能体架构

## 学习目标

把单一聊天 Agent 升级为 `Supervisor + Specialized Agents` 的协作模式。

## 本日实现

- `Supervisor Agent`：统一接收聊天请求，判断该交给哪个专家 Agent。
- `RAG Agent`：继续负责知识库检索、工具调用和 Agentic RAG。
- `Blog Agent`：回答博客、简历、项目经历、README 相关问题。
- `SQL Analysis Agent`：只返回安全聚合统计，例如文章数、文档数、会话数。
- `Writing Agent`：负责写作、总结、提纲、润色类任务。
- `Review Agent`：检查回答是否有引用、是否有幻觉风险、是否涉及敏感信息。
- `Admin Approval Agent`：拦截删除、权限、后台配置、敏感数据等高风险请求，给出人工审批建议。

## 后端改动

- 新增 `agent/multi_agent.py`。
- `/api/agent/chat/` 由 `MultiAgentSupervisor` 处理。
- API 响应新增 `supervisor` 字段：
  - `selected_agent`
  - `display_name`
  - `reason`
  - `confidence`
  - `handoff`
- `trace` 会记录 Supervisor 的路由过程。

## 前端改动

- 聊天消息中展示当前由哪个 Agent 处理。
- 右侧面板新增 Multi-Agent 清单。
- 工具面板支持展示：
  - `blog_agent_search`
  - `safe_sql_analytics`
  - `writing_outline`
  - `answer_review`
  - `admin_approval`

## 当前产出

一个多智能体协作版本：

```text
Supervisor Agent
├── RAG Agent
├── Blog Agent
├── SQL Analysis Agent
├── Writing Agent
├── Review Agent
└── Admin Approval Agent
```

用户仍然只需要在聊天框提问，系统会自动选择合适的专家 Agent，并在界面上展示路由结果。
