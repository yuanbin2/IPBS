# Day 9: Human-in-the-loop 人机审批

## 学习目标

让企业 Agent 在遇到高风险操作时暂停执行，先创建人工审批任务，管理员批准后才真正执行。

## 本日实现

- 新增 `ApprovalRequest` 审批模型。
- 新增审批 API：
  - `GET /api/agent/approvals/`
  - `POST /api/agent/approvals/<id>/`
- 新增前端审批后台：`/admin-approvals`。
- 敏感操作不再直接执行，而是返回 `202 Accepted` 并进入审批队列。

## 已接入审批的敏感操作

- 删除知识库。
- 删除知识库文档。
- 删除博客文章。
- 发布博客文章并同步知识库。

## 审批流

```text
用户触发敏感操作
  -> 后端创建 ApprovalRequest
  -> 前端提示已提交审批
  -> 管理员进入 /admin-approvals
  -> 批准或拒绝
  -> 批准后执行真实操作
  -> 记录执行结果
```

## 设计原则

- Agent 和普通用户不能黑盒执行高风险动作。
- 审批任务记录动作类型、请求人、payload、审批人、备注和执行结果。
- 发布和删除类操作都可追踪、可拒绝、可复盘。
- 当前版本用数据库持久化审批状态，后续可以接 LangGraph interrupt/checkpointer。

## 当前产出

企业级可控 Agent 雏形：

```text
Multi-Agent Supervisor
  -> Admin Approval Agent 判断高风险动作
  -> ApprovalRequest 持久化审批
  -> 管理后台人工批准
  -> 后端执行器执行敏感操作
```
