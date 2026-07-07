# Agent Workspace

这里放 LangChain、LangGraph、RAG、MCP 与评估相关代码。

## Day 2: LangChain Tool Calling

当前已经实现一个 LangChain Agent loop：

```text
用户输入 -> GPT-4o mini 判断工具 -> 调用 LangChain tool -> 汇总结果
```

已接入 3 个工具：

- `blog_search`：检索 README、架构文档和博客草稿
- `current_user_profile`：返回当前学习者和项目上下文
- `calculator`：执行简单四则运算

后端入口：

```text
POST /api/agent/chat/
```

当前已使用 LangChain 的 `ChatOpenAI` 和 `bind_tools`。还没有使用 LangGraph，后续会把单轮工具调用升级为状态图。

