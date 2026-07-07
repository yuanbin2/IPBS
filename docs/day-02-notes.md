# Day 2: LangChain Agent + Tool Calling

第二天目标是把第一天的工程底座继续推进到一个真正可对话、可调用工具的 Agent。

当前版本已经使用 **LangChain LCEL chain**，模型使用 `gpt-4o-mini`。它不再只是固定规则选择工具，而是可以先理解用户问题：

- 普通问题：模型可以直接回答
- 需要项目资料：调用 `blog_search`
- 需要用户上下文：调用 `current_user_profile`
- 需要计算：调用 `calculator`

## Agent 流程

整体链路：

```text
Vue /chat
  -> POST /api/agent/chat/
  -> Django AgentChatView
  -> SimpleToolCallingAgent
  -> LangChain LCEL chain
  -> gpt-4o-mini 判断是否需要工具
  -> 工具执行
  -> gpt-4o-mini 基于工具结果生成最终回答
```

代码里的 chain 结构：

```text
ChatPromptTemplate
  -> prompt | ChatOpenAI.bind_tools(...)
  -> AIMessage 或 AIMessage.tool_calls
```

如果模型决定调用工具：

```text
AIMessage.tool_calls
  -> 执行对应 LangChain tool
  -> ToolMessage
  -> MessagesPlaceholder
  -> final_prompt | ChatOpenAI
  -> 最终回答
```

如果模型不需要工具：

```text
AIMessage.content
  -> 直接返回普通问答结果
```

## 已完成

- 在 `agent/` 中实现 LangChain tool-calling agent
- 使用 `ChatOpenAI` 调用 `gpt-4o-mini`
- 使用 LCEL 写法组织 chain：
  - `tool_prompt | self.llm.bind_tools(self.tools)`
  - `final_prompt | self.llm`
- 使用 `bind_tools` 将 3 个工具绑定给模型：
  - `blog_search`：搜索 README、架构文档、博客草稿和 Day 2 笔记
  - `current_user_profile`：返回当前用户和项目上下文
  - `calculator`：执行简单四则运算
- Django 新增接口：`POST /api/agent/chat/`
- Vue 新增页面：`/chat`
- 前端支持展示工具调用名称、输入和输出
- 前端支持 `Enter` 发送消息，`Shift + Enter` 换行
- 外部模型不可用时，后端会降级到本地兜底工具，保证页面仍可用

## 为什么使用 Chain

这里使用 chain 的目的不是为了炫技，而是让 Agent 的每一段职责更清楚：

- `tool_prompt` 负责约束模型角色和工具使用策略
- `self.llm.bind_tools(self.tools)` 负责把工具 schema 暴露给模型
- `tool_chain` 负责完成“理解问题 + 判断是否调用工具”
- `final_chain` 负责完成“结合工具结果生成最终回答”

相比手写 if/else 路由，chain 结构让模型可以回答更开放的问题，也可以在需要时主动选择工具。

## 当前还没有使用 LangGraph

当前版本是 LangChain chain + tool calling，尚未使用 LangGraph。

LangGraph 更适合第三天要做的状态图工作流，例如：

```text
classify_question -> retrieve_or_direct -> generate_answer -> save_history
```

后续会把现在的单轮 Agent 改造成有状态的 LangGraph 工作流，并保存 conversation、message、agent_run 等历史记录。

