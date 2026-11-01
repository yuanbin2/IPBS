> **历史规划与迭代方法快照**：本文曾作为总体蓝图，内含旧目录、旧里程碑和文档地图，不是当前架构/状态真值。当前文档入口为 [文档索引](README.md)，完成度以 [缺陷跟踪表](缺陷跟踪表V2.0.md) 为准。

# Blog/Agent 系统设计蓝图与迭代手册

> 以下为 2026-09-23 撰写时的项目状态快照与治理提案；“当前系统完整度”、文档数量及开发路线均已过期，不能作为现状或完成度证据。
> 借鉴自 `lark-doc-content.md`（智控系统 V2.0 开发设计文档）的四大阶段框架与「面向对象数据空间」方法论，落地到当前 Django + LangGraph 系统。

---

## 0. 这份文档解决什么问题

撰写时（2026-09-23）的评估曾认为登录/RBAC/博客/RAG/对话/审批/工具/评估/可观测等主体已落地，并记录两个痛点。该清单、完成度和部署路径数量仅作历史记录，现状请对照源码、配置及缺陷表：

1. **文档散**：`docs/` 下 33 篇文档没有索引，不知道从哪看起。
2. **缺纪律**：没有统一的「功能编号」「维护责任」「更新日志」，改一处代码不会想到同步文档，导致（上一轮架构分析发现的）双份 `agent/` 源码、`models.py` 死代码这类问题长期存在。

本手册做三件事：**① 建立文档地图**（哪些文档是权威、哪些是过程产物）；**② 用对象数据空间 + 功能编号把系统「定死」**（数据在哪、谁维护）；**③ 建立「先文档后代码、改动必同步」的迭代纪律**（更新日志）。

---

## 一、需求分析

### 1.1 系统价值

| 问题 | 回答 |
| --- | --- |
| 用户是谁 | 本人（学习/求职）、未来的协作者、以及愿意试用这个 Agent 平台的用户 |
| 解决什么问题 | ① 把「个人博客内容」变成 Agent 可检索的私有知识；② 验证一套企业级 Agent 工程骨架（RBAC / RAG / 多智能体 / HITL / 可观测） |
| 与同类系统的关系 | 不是要做一个更强的 ChatGPT，而是做「**权限 + 检索 + 编排 + 治理**」四件事都真实落地的 Agent 底座 |
| 边界与扩展 | 当前边界：知识库问答 + 博客 + 工具调用 + 审批。扩展方向：更多数据源、更多 MCP 工具、多用户 workspace 隔离 |

### 1.2 开发目标

1. 所有人（包括 AI）能基于本文档**复现并理解**这个项目。
2. 每个数据「存在哪儿、什么格式、谁维护」都有共识，**不靠猜**。
3. 每次迭代都有迹可循：功能编号 → 数据空间 → 更新日志。
4. 重点关注：**触发条件、时间对齐、容错性**（对应 lark 的开发目标第 3 条）。

---

## 二、总体设计

### 2.1 文档地图（配套文档索引）

`docs/` 现有 33 篇文档，按「权威度」分三类。**只有「权威文档」需要维护同步，其余是过程产物，只读。**

| 类别 | 文档 | 说明 |
| --- | --- | --- |
| **总纲** | `design-blueprint.md` | 本文件，唯一入口，SSOT |
| **代码规范（权威）** | `coding-conventions.md` | 代码习惯 SSOT：模块划分、依赖方向、薄 View、API/错误统一格式、审查清单、代码层迁移路线图 C1–C11 |
| **架构（权威）** | `architecture-analysis.md` | 五层架构 + 技术债，与代码强绑定，需同步 |
| | `architecture.md` | 架构总览与图 |
| | `restful-async-architecture.md` / `project-structure.md` | 接口风格 + 目录结构 |
| **数据（权威）** | `database-schema-reference.md` | **字段级 schema 单一事实源** + 变更日志（字段以本文件为准） |
| | `models-design.md` | 模型设计详情，与 `models/` 包绑定 |
| | `database-design.md` / `database-er-diagram.md` | 数据库概念/逻辑设计 + ER 图 |
| **接口** | `api.md` | API 清单 |
| **部署** | `deployment.md` / `backend-deployment-guide.md` | 部署说明 |
| **评估** | `evaluation-report.md` / `repair-report.md` | 评估与修复记录 |
| **过程产物（只读）** | 旧版本曾有 `day-01` ~ `day-14` 开发日志 | 历史快照；这些路径已不在当前工作树中 |
| **求职/总结** | `job-preparation-guide.md` / `resume.md` / `python-fullstack-interview-guide.md` / `demo-script.md` / `final-blog-post.md` | 对外输出 |

> 规则：新增文档时，若属于「权威」，必须登记到本表；若属于「过程」，放入 `day-XX` 或单独归档，不要混进权威区。

### 2.2 设计思路：面向对象数据空间

核心原则（直接来自 lark 文档，逐条映射）：

| lark 原则 | 当前系统落地 |
| --- | --- |
| 以数据库为核心，所有人都知道数据在哪 | 以 Django `models/` 包为唯一数据定义源 |
| 面向对象划分数据空间 | 六大对象空间（见 2.3），与 `models/` 的 6 个领域文件一一对应 |
| 数据标准化 + 命名空间 | `workspace_key` 隔离 + 统一时间戳约定（见 2.4） |
| 业务/算法数据优先归到对象，无法归集才单开空间 | 新模型先考虑塞进 6 个现有空间，实在不行再新增空间 |
| 每份数据有「维护责任」 | 见 2.3 每空间的「维护责任」 |
| 日志自动清理（3 个月） | 见 2.4 待补项 |

**关键共识**：对象、算法、业务要分开看。数据「进入系统」由 RAG 摄入负责，「产出系统」由检索+生成负责，「编排」由 Supervisor/LangGraph 负责。这个三段式对应 lark 的「下城业务 / 上城业务 / 算法」。

### 2.3 六大对象数据空间（核心）

> 每个空间对应 `backend/apps/agent_api/models/` 下的一个领域文件。**模型字段变更 → 同步 `models-design.md` → 更新本手册日志**。

#### 对象 1：身份与权限（Identity & Access）

- 模型文件：`models/auth.py`
- 模型：`UserProfile`（用户扩展 + RBAC 角色）、`SecurityAuditEvent`（安全审计）
- 隔离键：`workspace_key`（对应 lark 的 `pid` 鉴权）
- 维护责任：**平台核心**（登录、鉴权、RBAC、审计是横切关注点）

#### 对象 2：内容与博客（Content & Blog）

- 模型文件：`models/blog.py`
- 模型：`ArticleCategory`、`ArticleTag`、`BlogArticle`、`BlogComment`、`BlogAgentSession`、`BlogAgentMessage`、`BlogAgentSecurityEvent`
- 维护责任：**博客 Agent**（公开内容，也是「个人经历」的检索来源）

#### 对象 3：知识库（Knowledge）

- 模型文件：`models/knowledge.py`
- 模型：`KnowledgeBase`、`Document`、`DocumentChunk`、`EmbeddingRecord`
- 维护责任：**RAG 摄入**（文档上传 → 切分 → 向量化 → 落库），对应 lark 的「下城业务」

#### 对象 4：对话与编排（Conversation & Orchestration）

- 模型文件：`models/agent.py`
- 模型：`Conversation`、`Message`、`AgentRun`
- 维护责任：**Agent 编排**（Supervisor 路由 + LangGraph 执行 + 会话持久化）

#### 对象 5：治理与工具（Governance & Tools）

- 模型文件：`models/governance.py`
- 模型：`ApprovalRequest`（审批流）、`MCPTool`（工具注册表）
- 维护责任：**治理层**（HITL 审批、工具权限、敏感操作拦截）

#### 对象 6：评估与可观测（Evaluation & Observability）

- 模型文件：`models/evaluation.py`
- 模型：`AgentObservation`（trace/延迟/成功率）、`EvaluationCase`（评估集）、`EvaluationRun`（评估运行）
- 维护责任：**评估**（质量度量 + 可观测）

### 2.4 数据标准化与命名约定

当前系统已有约定（来自 `models/README.md`，予以确认并扩展）：

| 约定 | 规则 | 状态 |
| --- | --- | --- |
| 表名 | Django 自动生成（`app_label + model` 小写），**不手动改表名**，保持 migration 稳定 | 已约定 |
| 隔离键 | 多租户业务数据必须带 `workspace_key`（`db_index=True`），私有会话再带所有者标识 | 已约定 |
| 时间戳 | 统一 `created_at`（auto_now_add）/ `updated_at`（auto_now），对应 lark 的 `update` | 已约定 |
| 状态枚举 | 固定状态用 `TextChoices` | 已约定 |
| 动态数据 | 动态执行详情用 `JSONField`（对应 lark「扩展表」的通用项/非标项思路） | 已约定 |
| 时序语义 | 对话/运行类按 `start`/`end` 表达区间（对应 lark 的 `start`/`end`） | 待补 |
| 日志自动清理 | 审计/观测日志自动过期删除（建议 3 个月） | 待补 |
| 软删除 | 关键业务数据（文章/文档）用软删除而非物理删除 | 待补 |

> 待补项已列入第六节的迭代路线图。

---

## 三、系统开发（功能清单）

### 3.1 编号规则

沿用 lark 的三级字母编号：**第一位 = 模块，后两位 = 子功能**。例如 `CAB` = 模块 C（知识库）下的第 2 个子功能（文档上传）。

模块划分（7 个）：

| 前缀 | 模块 | 对应对象空间 |
| --- | --- | --- |
| A | 身份与权限 | 对象 1 |
| B | 博客与内容 | 对象 2 |
| C | 知识库与 RAG | 对象 3 |
| D | 对话与编排 | 对象 4 |
| E | 治理与工具 | 对象 5 |
| F | 评估与可观测 | 对象 6 |
| G | 部署与运维 | 横切 |

### 3.2 功能清单

> 状态为初判（基于 README 与代码通读），用于快速定位「缺什么」；具体以实际验收为准。

#### A 身份与权限

| 编号 | 功能 | 状态 |
| --- | --- | --- |
| AAA | 账号登录 | 已实现 |
| AAB | 账号注册 | 已实现 |
| AAC | 登录页鉴权 | 已实现 |
| AAD | 退出登录 | 已实现 |
| AAE | 业务接口 JWT 鉴权（access 15min / refresh 7d） | 已实现 |
| AAF | 角色 RBAC（admin / operator / visitor） | 已实现 |
| AAG | workspace 多租户隔离 | 已实现 |

#### B 博客与内容

| 编号 | 功能 | 状态 |
| --- | --- | --- |
| BAA | 文章列表 / 详情 | 已实现 |
| BAB | 文章发布 / 编辑（含审批） | 已实现 |
| BAC | 分类与标签管理 | 已实现 |
| BAD | 评论 | 已实现 |
| BAE | 博客 Agent 会话 | 已实现 |

#### C 知识库与 RAG

| 编号 | 功能 | 状态 |
| --- | --- | --- |
| CAA | 知识库管理 | 已实现 |
| CAB | 文档上传（Celery 异步摄入） | 已实现 |
| CAC | 文档解析切分（900 / 重叠 140） | 已实现 |
| CAD | 向量化 embedding | 已实现 |
| CAE | 混合检索（0.72 向量 + 0.28 关键词） | 已实现 |
| CAF | 检索来源随回答返回（无独立引用生成节点；逐条依据性待人工验证） | 部分实现 |
| CAG | 三级降级路径（embedding / 向量库 / LLM） | 已实现 |

#### D 对话与编排

| 编号 | 功能 | 状态 |
| --- | --- | --- |
| DAA | 聊天对话 | 已实现 |
| DAB | 流式输出 SSE | 已实现 |
| DAC | Supervisor 关键词路由（15 级瀑布） | 已实现 |
| DAD | LangGraph 执行（含纠错回环） | 已实现 |
| DAE | 对话历史持久化 | 已实现 |
| DAF | AgentRun 记录 | 已实现 |
| DAG | Supervisor 路由单测 | 待补 |
| DAH | 对话项目（创建/重命名/删除/按项目过滤） | 已实现 |
| DAI | 对话归属项目与移动（新对话落入当前项目） | 已实现 |

#### E 治理与工具

| 编号 | 功能 | 状态 |
| --- | --- | --- |
| EAA | 工具注册表 | 已实现 |
| EAB | MCP 工具接入 | 已实现 |
| EAC | 工具调用审批 | 已实现 |
| EAD | 删除 / 发布审批流 | 已实现 |
| EAE | 敏感输入拦截（detect_sensitive_input，前置） | 已实现 |
| EAF | 输出脱敏 | 已实现 |

#### F 评估与可观测

| 编号 | 功能 | 状态 |
| --- | --- | --- |
| FAA | 评估集管理 | 已实现 |
| FAB | 评估运行 | 已实现 |
| FAC | Agent 观测（trace / 延迟 / 工具成功率） | 已实现 |
| FAD | 安全审计日志 | 已实现 |

#### G 部署与运维

| 编号 | 功能 | 状态 |
| --- | --- | --- |
| GAA | 本地一键启动（SQLite + 内存缓存 + Celery eager） | 已实现 |
| GAB | Docker Compose（Nginx + gunicorn + pgvector + Redis + RabbitMQ + Celery） | 已实现 |
| GAC | Railway 部署（根 Dockerfile） | 已实现 |
| GAD | Cloudflare Pages（静态前端） | 已实现 |
| GAE | 健康检查 | 已实现 |
| GAF | 配置管理（.env 多形态） | 已实现 |

### 3.3 迭代流程（先文档后代码）

> 直接来自 lark 文档 2.3.2 的核心纪律：「不写到文档就直接开发，坏处远大于好处」。

任何功能迭代，按以下顺序：

1. **登记**：在本手册功能清单里登记/更新功能编号（新增子功能取下一个字母，如 `DAG`）。
2. **设计**：若涉及数据，先在本手册对应对象空间 + `models-design.md` 写清字段、隔离键、维护责任。
3. **开发**：按设计实现；字段变更走 `makemigrations`。
4. **同步**：模型/接口有增删改 → 同步 `models-design.md` + `api.md`。
5. **记录**：在更新日志（第四节）登记日期 + 改动点 + 涉及文件。

---

## 四、收尾与维护

### 4.1 更新日志模板

每次迭代在下方追加一条（新→旧），格式：

```markdown
## YYYY.M.D
- 改动点
  - 涉及文件 / 模块
  - 影响的数据空间（对象 N）
```

#### 日志

## 2026.9.24
- 新增对话项目分组（DAH/DAI）：`ConversationProject` 模型 + `Conversation.project`（SET_NULL），项目 CRUD 与对话移动 API（`api.md` 已同步），侧边栏项目切换/新建/重命名/删除，新对话落入当前选中项目
  - 涉及文件 / 模块：backend/apps/agent_api/{models/agent.py, views/projects.py, api_urls/projects.py, serializers/agent.py, migrations/0027_*}、frontend/src/{views/AgentChatView.vue, features/chat/components/ConversationSidebar.vue, features/chat/types.ts, style.css}
  - 影响的数据空间：对象 4（对话与编排）新增 `ConversationProject` 表
  - 测试：新增 `tests/test_projects.py` 10 例，全量 102 例通过（5 个环境依赖既有失败不变）

## 2026.9.23（二）
- 执行 `coding-conventions.md` §9 代码层迁移 C1–C8（分支 `refactor/code-conventions-migration`，每项一个 commit）
  - C1 删除死代码（views.py / models.py / 根级 blog.py / blog_agent.py）；C2 删除根 `agent/` 重复包并合并搜索触发词、根 Dockerfile 去 `COPY agent`；C3 views 星号导入改显式（顺带修复 knowledge 视图潜伏 NameError）；C4 serializers 显式再导出 + `__all__`；C5 文章列表过滤下沉 `list_articles()`；C6 统一错误格式 `{detail, code}` + DRF exception_handler；C7 ruff/black 工具链 + CI 门 + pre-commit；C8 tests.py 拆 `tests/` 包 + 6 个 Supervisor 路由单测
  - 涉及文件 / 模块：横切全部模块；新增 `exceptions.py`、`pyproject.toml`、`.pre-commit-config.yaml`、`backend/requirements-dev.txt`
  - 影响的数据空间：无 schema 变更（对象 1-6 字段零变动，`makemigrations --check` 通过）
  - 测试基线：92 个测试；5 个环境依赖的既有失败（网络/embedding）迁移前后一致，无新增

## 2026.9.23（一）
- 新增 `coding-conventions.md`（代码规范手册，权威文档），登记进 2.1 文档地图与 4.2 同步约定
  - 涉及文件 / 模块：docs/coding-conventions.md（新增）、docs/design-blueprint.md（本条目）
  - 影响：横切全部模块（A–G）；代码层迁移路线图 C1–C11 与本表 T1–T9 对齐

### 4.2 变更同步约定

| 变更类型 | 必须同步的文档 |
| --- | --- |
| 新增/删除 Model 或字段 | `database-schema-reference.md`（字段 + 变更日志）+ `models-design.md` + 本手册 2.3 + 更新日志 |
| 新增/修改 API | `api.md` + 更新日志 |
| 架构/目录大改 | `architecture-analysis.md` + 更新日志 |
| 部署方式变化 | `deployment.md` + 本手册 G 模块 |
| 代码习惯/规范调整 | `coding-conventions.md` + 更新日志 |

### 4.3 迭代路线图（初始化：把已发现的技术债登记为待办）

> 来源：`architecture-analysis.md` 技术债清单，按优先级排序。
> 2026-09-23：T1/T2/T5 已随代码迁移完成（见下方「已完成」），T6 部分完成。

| 优先级 | 编号 | 待办 | 关联模块 | 状态 |
| --- | --- | --- | --- | --- |
| 高 | T1 | 合并 `agent/` 与 `backend/agent/` 双份源码（消除双部署代码分叉） | GAC / GAB | ✅ C2 |
| 高 | T2 | 删除 `models.py` 死代码（与 `models/` 包并存） | 对象 1-6 | ✅ C1 |
| 中 | T3 | Nginx 补 `proxy_buffering off`（修复 SSE 缓冲） | DAB / GAB | 待办 |
| 中 | T4 | 清理 4 个 desktop 目录（删 `desktop-app/` 空壳、统一 preload 键名） | G | 待办 |
| 中 | T5 | 补 Supervisor 路由单测（DAG） | DAC | ✅ C8 |
| 低 | T6 | 补后端单测（CI 已就绪但无测试） | 横切 | 🔶 部分：CI 已接 ruff/black 门 + tests 按域拆分 + 关键路径有测试；按域补满是持续项 |
| 低 | T7 | Celery Beat 清理（无 schedule，或删容器） | GAB | 待办 |
| 低 | T8 | `SecurityView.vue` 挂路由 | E / F | 待办 |
| 低 | T9 | 日志自动清理（3 个月）+ 软删除约定落地 | 对象 1 / 2 / 3 | 待办 |

---

## 五、与 lark 方法论的差异说明

| 维度 | lark（智控 2.0） | 当前系统 | 说明 |
| --- | --- | --- | --- |
| 数据库 | MongoDB + 时序 | PostgreSQL + pgvector | 「对象空间」在 lark 是 DB 命名空间，在这里是 Django models 领域文件 |
| 数据流 | IoT 设备实时采集（下城/上城） | 文档摄入 / 检索问答 | 「下城=摄入」「上城=生成」是类比映射 |
| 协作规模 | 多人（署名协作） | 单人为主 | 方法论同样适用，为未来协作预留 |
| 文档载体 | 飞书在线文档 | 本地 markdown（Git 版本化） | markdown 更适合 Git diff 追踪 |

**本质相通的一点**：lark 的核心不是技术选型，而是「**以数据为核心、对象分空间、责任到模块、改动必留痕**」的迭代纪律。当前系统缺的正是这一层纪律，而非技术能力。

---

*本手册随系统演进持续更新。当前版本初始化于 2026-09-23。*
