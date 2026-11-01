# 当前 API 索引

API 路由由 `backend/config/urls.py`、`backend/apps/agent_api/urls.py` 和 `api_urls/` 模块定义；本页列出主要路径族，不替代 serializer 的字段合同。路径默认以 `/api/agent/` 为前缀，健康检查为 `/api/health/`。

## 认证与权限

- 当前前端使用 `GET /auth/csrf/`，`POST /auth/cookie/login/`、`/auth/cookie/register/`、`/auth/cookie/refresh/`、`/auth/cookie/logout/`；旧式 `POST /auth/login/`、`/auth/register/`、`/auth/refresh/` 仍保留兼容路由。不要按旧文档把浏览器 JWT 写入 localStorage。
- `GET /auth/me/` 返回当前身份；`GET /security/status/` 与 `/security/audit-events/` 属于受控管理接口（仅 admin，且按 workspace 隔离）。
- `GET /security/audit-events/` 返回 `{ events, total, has_more }` 游标分页：`limit` 默认 20、上限 50，非法或越界值退回默认；`offset` 负值按 0 处理。前端安全页按 `-created_at, -id` 倒序滚动到底再取下一页。
- 注册只分配 visitor。operator/admin 权限由授权管理流程设置；生产请求依据认证用户 profile 的 workspace，不接受 `X-Workspace` 作为切租户授权。
- 私有笔记、会话和私有图片按 owner/workspace 校验；管理员权限不会自动绕过私有笔记所有权。各端点的匿名/角色规则以对应 View/Permission 与测试为准。

## API 路径族

| 领域 | 路径 | 说明 |
| --- | --- | --- |
| Agent | `/chat/`、`/chat/stream/`、`/chat/runs/<uuid>/`、`/conversations/`、`/projects/` | 对话、运行结果查询、会话与项目 |
| 知识库 | `/knowledge-bases/`、`/documents/`、`/knowledge-search/`、`/tasks/<id>/` | 文档上传/重建、搜索、异步状态 |
| 博客 | `/blog/articles/`、`/blog/articles/discover/`、`/blog/categories/`、`/blog/tags/`、`/blog/archive/`、`/blog/about/` | 文章、发现、分类、标签和公开信息 |
| HTML 导入 | `/blog/imports/html/preview/`、`/blog/imports/html/images/fetch/` | 校验预览、图片本地化辅助；不会绕过草稿/审核流程。旧 `/blog/imports/leetcode/link-preview/` 已于 2026-10-07 随力扣导入功能移除 |
| 私有笔记 | `/blog/notes/`、`/blog/notes/<id>/`、`/blog/notes/<id>/restore/` | 本人私有笔记、回收站恢复 |
| 私有图片 | `/blog/notes/images/`、`/blog/notes/images/<id>/` 等 | 上传、认证读回、绑定笔记 |
| 领域目录 | `/blog/collections/`、`/blog/collections/mine/`、`/blog/collections/<uuid>/...` | 公开目录、本人草稿、节点与文章条目维护 |
| 图片 | `/blog/images/`、`/media/blog/<name>` | 博客媒体上传及受控读取；私有笔记图不经公开路径读取 |
| 治理 | `/approvals/`、`/mcp-tools/` | 审批与受控工具管理/执行 |
| 评测与观测 | `/observability/`、`/evaluation-cases/`、`/evaluation-datasets/`、`/evaluation-batches/`、`/evaluation-runs/` | 观测、版本化数据集、异步批次与结果 |

博客文章提交发布、评论治理、举报、互动限制及写作 Agent 另有独立路由，详见 `backend/apps/agent_api/api_urls/blog.py`。**本索引故意不抄写完整方法/字段表**，避免与运行代码产生第二份失配合同。HTML 导入流程和测试入口见[文档索引](README.md)。

发布审批针对提交时的文章内容。待审的未发布文章发生编辑后，旧审批失效，需核对新内容并重新提交发布；已发布文章的修订继续按公开版本号单独审批。审批记录可在服务重启后查询，不能据此推断 LangGraph 节点可恢复；详见 [I-022 评估](I-022-草稿审批与恢复评估.md)。

## 问答运行状态（I-006）

- `POST /chat/` 与 `POST /chat/stream/` 可带客户端生成的 UUID `run_id`。同一用户、workspace、请求内容与 `run_id` 重试会复用原运行，不再写第二组消息、审批单或 AgentRun；同一个 ID 搭配不同请求返回 409。未传时后端生成 ID，但断开前若未收到响应，客户端将无法得知该 ID，因此前端主动生成并传入。响应体、SSE `run`/`done` 事件及 `X-Agent-Run-ID` 响应头均包含 ID。
- `GET /chat/runs/<uuid>/` 返回 `pending`（等待）、`running`、`succeeded`、`failed` 或 `cancelled`，以及消息 ID、取消请求、失败类别和成功结果。`POST /chat/runs/<uuid>/cancel/` 请求取消；两端点均要求 operator 权限及会话 owner/workspace 一致，不可跨用户读取。已结束的运行不会重新执行。
- `/chat/stream/` 的 SSE 顺序为 `run`（运行 ID 与状态）、零到多个 `progress`（阶段说明）、零到多个 `answer_delta`（真实模型正文片段）或 `answer_snapshot`（替换先前预览）、`response`（最终正文、引用和用量，已与消息及运行结果一同提交）、`done`（终态）。失败时发送 `error` 后发送 `done`，此时生成中看到的片段没有保存为助手消息。客户端按顺序拼接 delta，遇 snapshot 替换预览，最终以 response 正文为准。未提供生成期消息块的模型或工具路径只发送进度和完整 response，不模拟逐字输出。成功结果记录 `first_body_ms`（首次正文增量延迟，无增量为 `null`）与 `latency_ms`（总耗时）。
- 前端“停止接收”只关闭本次 HTTP 响应，不调用取消接口；“请求取消执行”才调用 `POST /chat/runs/<uuid>/cancel/`。流式迭代器在正常关闭时会继续消费模型输出并提交终态；测试客户端模拟断线后可按 `run_id` 找回结果。真实网络断连和进程强杀尚未验收。取消等待中的运行会立即变成 `cancelled`；取消运行中的任务只设置 `cancel_requested`，生成期在可观察到下一片段时检查并尽快停止，当前阻塞中的模型/工具调用无法强制中断。取消接口返回 `running` 加 `cancel_requested: true` 不表示执行已停止。前端在正文尚未完整时以纯文本预览，收到最终结果后再渲染 Markdown。
- 运行超过默认 900 秒未更新时，下一次按 ID 查询会把遗留的等待/运行状态标为 `failed`（`error_code: interrupted`）；已请求取消的遗留运行转为 `cancelled`。这是超时判定，不能证明进程何时退出；后到的结果不得覆盖终态。旧 AgentRun 数据迁移后默认 `succeeded`，可从已有观测记录回读可用结果。
