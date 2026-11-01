# 后端 Agent 运行时代码

该 Python 包由 Django Agent API 和 Celery 任务调用，是当前后端 Agent/RAG 的代码实现之一；它不是仓库根目录的旧学习日程。入口包含 `multi_agent.py`、`simple_agent.py`、`security.py`、`rag_tools.py`、`mcp_tools.py` 和 `specialized_agents.py`。具体调用由 `backend/apps/agent_api/views/chat.py`、`views/common.py`、`tasks.py` 与测试覆盖。

旧文档中“Day 2 GPT-4o mini 固定工具循环”“三工具清单”已过时；当前供应商、路由和权限按运行配置与 Agent 服务实现，不应从本文推断默认模型或生产能力。开发入口见仓库[README](../../README.md)，架构和未验证范围见[当前架构](../../docs/architecture.md)与[缺陷跟踪表](../../docs/缺陷跟踪表V2.0.md)。
