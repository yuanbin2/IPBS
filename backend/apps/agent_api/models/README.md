# Django 模型层

本目录是 `agent_api` Django App 的模型包。按领域拆分 Python 文件，但保留同一 app label 与迁移空间。`__init__.py` 统一导出模型，迁移位于 `backend/apps/agent_api/migrations/`。

| 文件 | 当前领域 |
| --- | --- |
| `agent.py` | 对话、项目、消息、运行记录 |
| `auth.py` | 用户角色/工作空间 profile、安全审计 |
| `knowledge.py` | 知识库、文档、切片、embedding、入库任务 |
| `blog.py` | 博客文章与修订、评论治理、私有笔记/图片、领域目录 |
| `governance.py` | 审批与 MCP 工具 |
| `evaluation.py` | Agent 观测、评测用例/运行/数据集/批次 |

修改流程：更新模型后在仓库根运行 `.venv\Scripts\python.exe backend\manage.py makemigrations`（POSIX 使用 `.venv/bin/python backend/manage.py ...`），检查并提交生成的 migration，再运行对应迁移和模型/API 回归。不要手工修改已应用迁移。Workspace 与 owner 的实际约束按字段、View 权限和测试核对；旧的字段示例与规划不覆盖代码。

当前数据库运行模式与私有/公开媒体边界见[数据库说明](../../../../docs/database-current.md)。字段变更以模型 + migrations + 测试为事实来源。
