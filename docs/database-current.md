# 当前数据库与媒体边界

本页是数据库的**当前概览**，以 Django 模型和迁移为事实来源。模型在 `backend/apps/agent_api/models/`；迁移在 `backend/apps/agent_api/migrations/`。字段类型、索引、约束如与旧设计文档冲突，始终以当前模型、迁移和对应测试为准。不要把 SQLite 本地模式指标当作 PostgreSQL/pgvector 生产验收。

## 数据库运行模式

- 根目录 `start.bat` / `start.sh` 与 `restart*.ps1` 显式启用 `BLOG_LOCAL_MODE=true`，使用 `backend/db.sqlite3`。该模式用于开发/演示。
- Compose 将 `DATABASE_URL` 指向 PostgreSQL 16，并使用 `pgvector/pgvector:0.8.6-pg16`。向量存储/索引由迁移和 `backend/apps/agent_api/services/vector_store.py` 管理；PostgreSQL 之外不应切换成 pgvector 模式。
- Compose Redis 提供缓存/任务结果，RabbitMQ 是 Celery broker。异步任务持久性、生产 worker 配置仍需实站验收。

## 当前模型领域

模型按源文件分组；模型类与表名用代码搜索，而不是依赖旧字段清单：

| 源文件 | 当前领域示例 |
| --- | --- |
| `models/auth.py` | `UserProfile`、`SecurityAuditEvent` |
| `models/agent.py` | `ConversationProject`、`Conversation`、`Message`、`AgentRun` |
| `models/knowledge.py` | `KnowledgeBase`、`Document`、`DocumentChunk`、`EmbeddingRecord`、`DocumentIngestionJob` |
| `models/blog.py` | 文章、修订、分类/标签、评论治理、私有笔记/图片、博客 Agent、领域目录 |
| `models/governance.py` | `ApprovalRequest`、`MCPTool` |
| `models/evaluation.py` | `AgentObservation`、评测用例/运行、数据集、批次和逐题结果 |

具体字段和删除语义请直接查看模型定义、迁移及测试；仓库中的旧 schema 手册与 ER 图不完整，已从当前规范入口撤下并标注历史参考。

## 身份、权限与私有数据

`UserProfile` 保存角色和 `workspace_key`；公开注册创建 visitor。多租户业务表仍主要用 `workspace_key` 表示工作空间，不能假设存在完整成员/邀请关系模型。私有笔记还按稳定用户 owner 限制读写；管理员不会默认越权查看他人笔记。

`PrivateNoteImage` 的文件根目录与公开 `MEDIA_ROOT` 分离，API 读回验证 owner/workspace。Compose 挂独立 `private_note_data` 卷，前端 Nginx 不挂载。公开文章图片由 `/media/blog/<name>` 的后端读取视图代理，实际文件通过可配置存储后端提供。生产 S3/Railway Bucket 持久性与恢复仍待验证。

## 验证

- 当前状态与遗留迁移风险：[缺陷跟踪表](缺陷跟踪表V2.0.md)
- 迁移定义：`backend/apps/agent_api/migrations/`
- ORM 字段：`backend/apps/agent_api/models/`
- 本地迁移命令：`python backend/manage.py showmigrations`；不要对生产库执行迁移或媒体搬迁，除非按部署/备份流程完成批准与备份。
