# Day 3: LangGraph 基础图工作流

第三天目标是把第二天的 LangChain chain + tool calling Agent 改造成 LangGraph 状态图工作流，并把聊天历史持久化。

## 学习目标

- 理解 `StateGraph`
- 理解 node、edge、conditional edge
- 理解为什么复杂 Agent 更适合用图来表达流程

## 当前工作流

代码位置：`agent/simple_agent.py`

图结构：

```text
classify_question
  -> conditional edge
    -> retrieve_or_direct
    -> generate_answer
  -> save_history
  -> END
```

更完整的流程：

```text
用户输入
  -> classify_question
  -> 如果需要项目资料 / 用户资料 / 计算：retrieve_or_direct
  -> 如果是普通问题：generate_answer
  -> save_history
```

节点说明：

- `classify_question`：判断问题是否需要工具或项目上下文。
- `retrieve_or_direct`：通过 LangChain `bind_tools` 调用工具。
- `generate_answer`：生成最终回答。
- `save_history`：在图中标记持久化节点，实际保存由 Django ORM 完成。

## 已完成

- 使用 LangGraph `StateGraph` 重构 Agent。
- 增加条件边：普通问题直接进入大模型回答，工具型问题进入工具调用节点。
- 保留 LangChain LCEL chain：
  - `ChatPromptTemplate | ChatOpenAI.bind_tools(...)`
  - `ChatPromptTemplate | ChatOpenAI`
  - `MessagesPlaceholder | ChatOpenAI`
- 后端新增持久化表：
  - `Conversation`
  - `Message`
  - `AgentRun`
- 后端新增历史接口：
  - `GET /api/agent/conversations/`
  - `GET /api/agent/conversations/<id>/`
- 前端聊天页支持刷新后加载历史记录。
- 前端聊天区域改为滚动容器，导航栏固定。
- 前端历史记录支持搜索。
- 历史消息按固定数量分页加载，默认每次最多加载 30 条；向上滚动可以继续加载更早消息。
- 搜索历史命中后可以跳转到对应消息附近。
- 接入 LangSmith tracing，用于观察模型调用、chain、graph 和工具调用 trace。
- 前端展示每次回答的 token 消耗，包括 prompt、completion 和 total tokens。

## LangSmith 配置

本地 `.env` 中开启：

```text
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=knowledge-agent-day3
```

同时保留兼容变量：

```text
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=...
LANGCHAIN_PROJECT=knowledge-agent-day3
```

这样 LangChain / LangGraph 运行时的模型调用、chain 执行和工具调用会被发送到 LangSmith 项目中，便于观察 trace、延迟、错误和 token 使用情况。

## Token 消耗展示

后端会从 LangChain 返回的消息元数据中读取 token 用量：

```text
usage_metadata 或 response_metadata.token_usage
```

然后聚合成本轮回答的：

```text
prompt_tokens
completion_tokens
total_tokens
```

这些数据会随 `POST /api/agent/chat/` 返回，并保存到 `Message.token_usage` 和 `AgentRun.token_usage`。前端在回答生成过程中显示“统计中”，收到响应后展示实际 token 消耗。

## 为什么 LangGraph 更适合第三天

第二天的 Agent 是线性 chain，适合演示工具调用。

第三天开始，Agent 需要明确流程控制：

- 先分类问题
- 决定是否检索或调用工具
- 再生成答案
- 最后保存历史

这些步骤天然适合用图来表达。后续如果加入人工审批、失败重试、多智能体协作、长期记忆，LangGraph 的状态管理和条件边会比单条 chain 更清晰。

## 未解决问题

当前 Agent 的 RAG / 工具调用逻辑还需要继续优化：检索到的项目文档结果应该作为最终提示词的一部分交给大模型综合回答，而不是让回答完全依赖文档命中结果。

期望行为：

- 普通问题，例如“天上有多少颗星星”，应直接调用 `gpt-4o-mini` 生成回答。
- 需要项目上下文的问题，应先检索文档，再把检索结果作为上下文放进 prompt，由大模型生成最终答案。
- 如果文档上下文不足，大模型仍然可以基于通用知识回答，并说明哪些内容来自上下文、哪些是补充判断。
- 不应该因为本地文档没有命中就返回“数据库中没有”或“无法回答”。

下一步应重点检查 `agent/simple_agent.py` 中 `retrieve_or_direct -> generate_answer` 的数据流，确保工具输出只是增强上下文，而不是答案边界。
