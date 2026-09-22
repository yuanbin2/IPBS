# Agent Workspace

这里放 LangChain、LangGraph、RAG、MCP 与评估相关代码。

## Day 2: LangChain Tool Calling

第二天实现了 LangChain Agent loop：

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

## Day 3: LangGraph StateGraph

当前 Agent 已升级为 LangGraph `StateGraph`：

```text
classify_question -> retrieve_or_direct -> generate_answer -> save_history
```

其中 `classify_question` 后面有 conditional edge：

- `retrieve`：需要项目资料、当前用户资料或计算，进入工具节点
- `direct`：普通问题直接生成回答

聊天历史由 Django ORM 保存到 `Conversation`、`Message`、`AgentRun`。

