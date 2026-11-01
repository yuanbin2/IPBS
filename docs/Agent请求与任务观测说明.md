# 请求、任务与模型调用观测（I-012）

## 关联方式

| 路径 | 关联键 | 查询位置 |
| --- | --- | --- |
| HTTP | 服务端生成 `X-Request-ID`，不接受客户端伪造的值 | 响应头；安全的 `request_completed` 日志。SSE 头返回时记 `response_started`，生成结束以 run 状态为准。 |
| 问答 | `AgentRun.request_id` → `run_id` → `model_calls[].call_id` | 已授权用户按 `run_id` 查询运行记录；`stage_timings` 和 I-005 模型记录同在 run 内。重复请求保留原始执行的 request_id，不重复执行；新 HTTP 请求另有 `X-Request-ID`，`run_reused` 事件以 run_id 关联两者。 |
| 本地文档上传 | 上传 request_id → `DocumentIngestionJob.id`（同时为 Celery task_id）→ 文档 id | 上传响应、`/api/agent/tasks/<task_id>/`、入库任务及日志。重试沿用同一个 task_id。 |

问答 `stage_timings` 记录 `queue_wait_ms`（run 创建至开始）、`retrieval_ms`（当前 RAG 检索调用之和）、`model_ms`（I-005 语言模型调用耗时之和）、`total_ms` 与调用次数。`largest_measured_stage` 从前三类选最大值；它只是定位线索，不能当成完整火焰图。检索中发生的 embedding 计入检索阶段，同时产生独立的 `embedding` 日志事件。入库 `timings` 记录最近一次 `queued_at`、`queue_wait_ms`、`last_processing_ms`、`last_embedding_ms` 及累计处理和 embedding 毫秒数；`attempts` 和安全错误码在同一任务记录中。直接执行而没有投递时间的任务以创建时间为排队起点。处理耗时包含解析、向量化和索引激活。本地哈希与远程 embedding 均有阶段耗时；远程 embedding 服务商用量和价格尚未接入 I-005 的语言模型统计，不能由耗时推算 token 或费用。

日志只允许标识、固定事件名、状态/错误类别、计数和毫秒数；未知错误码归为 `other_failure`。异常正文、提示词、文档内容、模型输入输出、API Key、上传文件名均不进入新观测日志。`AgentRun` 与 `Document` 的业务正文仍按原功能存储，必须继续受原有用户、角色与 workspace 权限约束。按 run_id 查询要求所有者及 workspace；文档任务状态要求 operator 权限与同一 workspace，其他 workspace 的任务返回 404。日志仅供有服务端或容器日志权限的运维人员访问，不作为公开 API。日志中的 request_id 不能用作授权凭据。

## 失败告警与留存

终态问答失败和文档入库耗尽重试时写入 `failure_alert` ERROR 事件，重复终态检查不会重复告警。设置 `AGENT_ALERT_EMAILS` 后同时发简短邮件，SMTP 使用 `AGENT_ALERT_SMTP_HOST/PORT/USER/PASSWORD/TLS`，`AGENT_ALERT_FROM_EMAIL` 与 3 秒默认超时；未配置收件人时保留 ERROR 日志。邮件发送失败只写 `alert_delivery_failed`，不改变原业务状态。请把收件人设为受控运维邮箱；不要把邮件指向公开列表。

Compose 的 backend 与 Celery worker 控制台日志各限制为 `json-file` 10 MB × 3 个文件；本地运行及其他托管平台由宿主日志系统决定保留期，需单独配置访问与轮转。运行记录和入库任务记录在业务数据库中，当前随所属会话/文档生命周期保存，没有独立自动 TTL；邮件留存由邮件服务策略决定。生产环境的收件人、SMTP 投递、容器日志权限、保留策略和告警到达时间仍需实测。

## 验证边界

隔离回归的一组关联样例（UUID 来自临时测试数据库，测试结束即销毁）：

| 路径 | request_id | run_id / task_id | 关联事件与结果 |
| --- | --- | --- | --- |
| 上传 | `623e0f57-bd32-4748-8342-87f844700c5d` | task_id `6346cb78-48fa-4e9d-b67c-bc5e7078d3e7` | `ingestion_scheduled` → HTTP 202；任务记录和查询接口返回同一 request_id。 |
| 问答 | `2a2b4303-7045-4d48-9649-07c92b898ebb` | run_id `0e45214d-6b77-4733-be38-13bc9a239530` | `stage_completed` 检索 → `chat_stages` 成功：排队 2 ms、检索 0 ms、语言模型 1 ms、总计 360 ms；一条 mock 模型调用的记录携带同一 request_id/run_id。毫秒整数取整，0 不表示未执行。 |

这两条是 mock/本地 SQLite 验证样例，不能代表真实服务性能；其余 357 ms 含路由、模拟回答和框架开销。

隔离 Django 测试数据库及内存邮件后端已触发一次问答超时和一次入库终态故障，验证两个告警均携带 request_id 与 run_id/task_id，不含私有正文或异常消息。此验证不会发送外部邮件。队列/worker 的真实 RabbitMQ 与 PostgreSQL、生产邮件投递、日志聚合和真实模型耗时尚未实测。当前检索阶段计时覆盖本地 RAG 的 `search_sources`；外部 RAG-Agent、独立公开访客博客、写作助手及评测任务仍需按各自运行记录补齐，不能从缺少阶段事件推断耗时为零。
