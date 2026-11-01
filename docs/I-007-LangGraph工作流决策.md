# ADR I-007：保留有限 LangGraph 问答图，清理空节点

日期：2026-10-23。状态：**已作代码层决策；效果与性能待验证**。

## 现状与职责

`POST /api/agent/chat/` 先在 Django 层校验用户、workspace、会话与工具权限，并用 `AgentRun` 建立运行记录。`MultiAgentSupervisor` 做敏感输入前置拦截和 `supervisor_routing.decide()` 规则分发；其“置信度”是硬编码标签，不是模型概率。所谓 blog、SQL、MCP、review、approval、RAG 等“Agent”是专用处理函数/服务，并非多个模型自主商议、规划或协作。MCP 执行前还要检查 workspace 内工具注册、启用与审批；路由命中本身不授权工具。

只有分到 `rag_agent` 的请求进入 `SimpleToolCallingAgent` 图。当前五节点：`query_analyzer → retrieve → grade_documents → [rewrite_query → retrieve，最多一次] → generate → END`；`query_analyzer` 的 direct 分支直接到 `generate`。查询是否检索、来源阈值 `0.12`、是否重写、最大次数 `1` 都是规则。原 `cite_sources` 只追加 trace，不创建/核验引用，本次删除；检索来源从状态进入响应与 `AgentRun`。相关性边界现在由纯函数 `rag_tools.grade_source_relevance()` 供图和异常兜底共用，能脱离图测试。

模型调用与图节点不同：有历史的检索追问可能在 `query_analyzer` 调查询改写模型；`retrieve` 在确定性扩展不适用且配置模型时可能调扩展模型，并调用知识库检索（embedding 本身可能是远端模型）；低相关第二轮的 `rewrite_query` 可能调改写模型；`generate` 在有模型的直接回答或有可靠来源的 RAG 回答时调生成模型。无来源、确定性工具和无模型兜底不应被描述为模型推理。公开博客、联网合成和写作的模型调用发生在图外的专用路径。

图内 `AgentState` 是**单次调用内存状态**，记录 query、sources、tool_calls、rewrite_count、answer 与 trace；`compile()` 没有 checkpointer。`max_rewrites=1` 只限制低相关检索回环，不是故障自动重试。ChatOpenAI 由 `llm_support` 设置 `max_retries=0`，以免 SDK 隐藏重试用量；查询改写/扩展失败可能走确定性兜底，模型超时向上抛出。API 层的 `AgentRun` 管理 pending/running/succeeded/failed/cancelled、幂等 run_id、结果/消息持久化和过期运行识别；取消为当前步骤后协作式生效。**聊天记录和 AgentRun 可查，不等于 LangGraph checkpoint，也不能从中途节点恢复执行。**

## 选择与证据

**短期保留这个有限图，不扩张为更多 Agent 图。**当前同步/流式接口已经依赖相同节点状态，流式正文按 LangGraph `messages` 中的 `generate` 节点识别；立即改成普通函数要重新验证增量事件、最终正文、用量回调和失败持久化。移除空的 `cite_sources` 节点可降低一层无意义状态转换，同时保持现有分支、来源和输出接口。锁定依赖为 `langgraph==0.2.76`、`langchain-core==0.3.86`、`langchain-openai==0.2.14`（本地安装版本一致），本次不升级。

| 比较项 | 普通函数流程 | 当前有限图 | 已有证据与缺口 |
| --- | --- | --- | --- |
| 维护 | `if/else` 与一次有界循环足以表达现有五步，少一个框架和图状态映射 | 分支/回环可视化，但每个节点传完整状态、同步与流式事件需分别组装，增加认知与回归成本 | 这是代码结构比较，未量化维护工时 |
| 效果 | 业务规则与检索/模型相同时理论上应得同样答案 | 图本身不提高召回或依据性 | I-001 仅合成语料/本地哈希、暂定标注；复杂检索链未优于关键词基线，不能归因为图；真实 embedding/人工答案评测未完成 |
| 性能/费用 | 无图调度；节省多少、占总耗时比例均未测 | 有节点调度与状态传递；最多一次低相关改写可增加模型/检索调用 | I-002 的 mock 路径计时不是同条件图/函数对照；I-013 没有可用 PostgreSQL，尚无真实检索计划、P50/P95；没有端到端 A/B 或准确成本差值 |
| 运行能力 | 手写状态、进度与流式模型事件仍可实现 | 现有 `messages` 事件已用于生成节点增量；没有 checkpoint/HITL 恢复能力 | I-004 的一次真实模型流式样本只证明可输出片段，不证明图比函数更快或更准 |

若人工复核的 I-001 样本、真实 embedding、I-013 PostgreSQL 与同条件端到端 A/B 之后，函数版在权限、答案、来源、SSE 增量、用量、失败/取消结果上等价，且维护或性能确有收益，再考虑替换当前图。不能用 SQLite/mock 时延代替线上结论。

## 未来引入 checkpoint / 人工中断的门槛

先要有真实跨请求业务步骤，例如“带来源草稿 → 指定用户修改/批准 → 发布”，且需要进程重启后从明确节点恢复。届时先明确审批人、workspace 权限在**恢复时重新校验**、草稿与 run_id 的关联、状态版本、外部副作用幂等键、重复恢复与撤销、过期和清理策略；选择与锁定版本兼容的持久化 checkpointer，并在隔离库验证中断、重启、拒绝、权限撤销和重复发布。现有 `ApprovalRequest`/聊天记录只保存业务记录，不能视作图中断点。没有这些需求和测试，不增加 checkpoint 或框架版本。

## 本次验证与未验证

新测试核对纯相关性边界、图节点与来源保留、低相关最多一次改写；并运行聊天、知识库、多轮、SSE、run 状态等相关回归。结果和具体命令记入改进表实施记录。真实模型回答依据性、函数/图同条件延迟与成本、真实 PostgreSQL 和进程重启恢复未验证；ADR 的“保留”是当前兼容性与变更风险决策，**不是图带来质量提升的证明**。
