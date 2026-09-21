# Models 模型层

本目录是 `agent_api` 的独立数据模型层。模型仍属于同一个 Django App，因此拆成 Python
包而不是移动到项目根目录：这样既能按业务领域分文件，也能保持既有 migration、app label
和数据库表名稳定。

## 文件职责

| 文件 | 领域 | Model |
|---|---|---|
| `agent.py` | 私有对话与 Agent 执行 | `Conversation`、`Message`、`AgentRun` |
| `auth.py` | 用户扩展与安全审计 | `UserProfile`、`SecurityAuditEvent` |
| `knowledge.py` | 知识库与向量检索 | `KnowledgeBase`、`Document`、`DocumentChunk`、`EmbeddingRecord` |
| `blog.py` | 博客与公开博客 Agent | `ArticleCategory`、`ArticleTag`、`BlogArticle`、`BlogComment`、`BlogAgentSession`、`BlogAgentMessage`、`BlogAgentSecurityEvent` |
| `governance.py` | 审批和 MCP 工具治理 | `ApprovalRequest`、`MCPTool` |
| `evaluation.py` | 可观测性与评测 | `AgentObservation`、`EvaluationCase`、`EvaluationRun` |
| `constants.py` | 模型共享常量 | 默认工作空间等 |
| `__init__.py` | 对外统一导出 | 保持 `from apps.agent_api.models import ...` 的稳定导入方式 |

完整字段设计、设计原因、关系图和示例数据见
[`docs/models-design.md`](../../../../docs/models-design.md)。

## 修改规则

1. View、Serializer、Service 不直接定义数据库字段。
2. 新模型放入对应领域文件，并在 `__init__.py` 导出。
3. 字段或关系变化后执行 `python manage.py makemigrations`。
4. 多租户业务数据应带 `workspace_key`，私有会话还应带所有者标识。
5. 固定状态使用 `TextChoices`；动态执行详情可使用 `JSONField`。
