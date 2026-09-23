# 数据库字段参考手册（Database Schema Reference）

> 本文件是系统**字段级 schema 的单一事实源**。参考 `lark-doc-db-design.md`（智控系统数据库设计文档）的方法论：按对象空间组织、字段级设计、标准约定、变更追踪。
> 字段以本文件为准；代码（`models/` 包）是最终实现，但**任何字段增删改必须同步本文件**。

---

## 0. 文档定位与分工

当前系统有三份数据库相关文档，分工如下（避免「文档散」）：

| 文档 | 定位 | 回答的问题 |
| --- | --- | --- |
| **`database-schema-reference.md`（本文件）** | 字段级 schema + 变更日志 | 每张表有哪些字段、什么类型、怎么索引 |
| `database-design.md` | 概念/逻辑设计 | 为什么这样分领域、概念模型长什么样 |
| `models-design.md` | 设计意图 | 为什么拆 models 包、每个 model 的设计理由 |
| `database-er-diagram.md` | ER 图（mermaid） | 表之间的关系视图 |

**唯一真值链**：`models/*.py`（实现）←→ 本文件（字段字典）←→ `database-design.md`（概念）。三者不一致时，以代码为准并**立即同步文档**。

> **例外**：`agent_api_vectorindex`（pgvector 表）不走 ORM，由 `services/vector_store.py` 原生 SQL 建表，其唯一真值是 `vector_store.py` + 本文件 3.5 节，不经过 migration。

---

## 1. 标准字段约定（对应 lark 标准头部）

lark 文档型数据库每表带 `pid/oid/start/end/update` 五个标准头部。当前系统是 Django 关系型，映射如下：

| lark 标准头部 | 当前系统落地 | 说明 |
| --- | --- | --- |
| `pid`（项目 ID） | `workspace_key`（CharField 80，db_index） | 多租户隔离键，所有业务数据必带 |
| `oid`（对象 ID） | 外键字段（FK） | 关系型用外键表达对象归属 |
| `update`（更新时间） | `updated_at`（auto_now） | 统一更新时间戳 |
| `start` / `end`（区间） | 具体时间字段 | 如 `published_at` / `reviewed_at`，关系型不强制统一 |

**统一约定**（已落地于 `models/README.md`）：

1. 多租户业务数据必须带 `workspace_key`（`db_index=True`）；私有会话再带所有者标识（如 `owner_username`）。
2. 时间戳统一 `created_at`（auto_now_add）/ `updated_at`（auto_now）。
3. 固定状态用 `TextChoices`；动态执行详情用 `JSONField`。

---

## 2. 命名与类型约定

### 2.1 表命名（对应 lark「功能前缀 + 时间粒度后缀」）

lark 用 `pv_std_status_15min`（对象_类型_粒度）。Django 表名由 `app_label + model 小写` 自动生成（如 `agent_api_document`），**不手动改表名**。因此命名规范落在 **model 类名**上：

| lark 前缀 | 当前系统 model 命名 | 示例 |
| --- | --- | --- |
| 对象前缀 | 领域前缀 | `BlogArticle`（博客）、`DocumentChunk`（知识库） |
| 类型前缀 | 实体名直白 | `AgentRun`、`ApprovalRequest` |
| 时间粒度后缀 | 无（关系型不按时间分表） | 时序粒度由数据内容决定，不拆表 |

### 2.2 字段类型约定（对应 lark「字段含单位 / 数据类型约定」）

| 场景 | 约定 | 示例 |
| --- | --- | --- |
| 固定状态 | `TextChoices` 枚举 | `Status.PENDING` / `Role.USER` |
| 动态结构 | `JSONField` | `trace`、`tool_calls`、`payload`、`metrics` |
| 布尔 | `is_` 前缀 | `is_enabled`、`is_archived`、`is_approved` |
| 外键 | 实体名单数 | `knowledge_base`、`conversation`、`case` |
| 计数 | `_count` 后缀 | `call_count`、`chunk_count`、`view_count` |
| 时间点 | `_at` 后缀 | `published_at`、`reviewed_at`、`executed_at` |

---

## 3. 六大对象空间 · 字段级设计

> 每张表列出：Django 表名、模型文件、维护责任、字段清单、状态枚举、索引。
> 「维护责任」对应 `design-blueprint.md` 的对象空间划分。

### 对象 1：身份与权限（`models/auth.py`）

#### 1.1 `UserProfile` 用户扩展

- 表名：`agent_api_userprofile` ｜ 维护责任：平台核心
- 作用：在 Django 内置 `auth.User` 上扩展角色与工作区

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `id` | PK | 主键 | 自动 |
| `user` | OneToOne → `auth.User` | 关联内置用户 | CASCADE |
| `role` | CharField(20) | 角色 | 枚举，默认 `visitor` |
| `workspace_key` | CharField(80) | 工作区隔离键 | 默认 `default`，db_index |
| `created_at` / `updated_at` | DateTimeField | 时间戳 | auto |

- 角色枚举：`admin` / `operator` / `visitor`
- 索引：`(user_id)`（OneToOne 唯一）、`workspace_key`

#### 1.2 `SecurityAuditEvent` 安全审计事件

- 表名：`agent_api_securityauditevent` ｜ 维护责任：平台核心

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `id` | PK | 主键 | 自动 |
| `event_type` | CharField(40) | 事件类型 | 枚举 |
| `actor` | CharField(120) | 操作者 | blank |
| `role` | CharField(20) | 角色 | blank |
| `workspace_key` | CharField(80) | 隔离键 | db_index |
| `path` | CharField(240) | 请求路径 | blank |
| `detail` | TextField | 详情 | blank |
| `metadata` | JSONField | 附加信息 | 默认 `{}` |
| `created_at` | DateTimeField | 时间戳 | auto |

- 事件枚举：`login` / `access_denied` / `sensitive_input` / `output_redacted` / `tool_blocked`
- 索引：`workspace_key`，排序 `-created_at`

---

### 对象 2：内容与博客（`models/blog.py`）

#### 2.1 `ArticleCategory` 文章分类

表名 `agent_api_articlecategory` ｜ 责任：博客 Agent

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `name` | CharField(80) | 分类名 | unique |
| `slug` | SlugField(100) | 别名 | unique，allow_unicode |
| `description` | TextField | 描述 | blank |
| `created_at` | DateTimeField | 时间戳 | auto |

#### 2.2 `ArticleTag` 文章标签

表名 `agent_api_articletag` ｜ 责任：博客 Agent

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `name` | CharField(60) | 标签名 | unique |
| `slug` | SlugField(80) | 别名 | unique，allow_unicode |
| `created_at` | DateTimeField | 时间戳 | auto |

#### 2.3 `BlogArticle` 博客文章

表名 `agent_api_blogarticle` ｜ 责任：博客 Agent

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `title` | CharField(180) | 标题 | 必填 |
| `workspace_key` | CharField(80) | 隔离键 | db_index |
| `slug` | SlugField(220) | 别名 | unique，allow_unicode |
| `author_name` | CharField(80) | 作者 | 默认 `""` |
| `summary` | TextField | 摘要 | blank |
| `cover_image` | TextField | 封面图 | 默认 `""` |
| `content` | TextField | 正文 | 必填 |
| `category` | FK → `ArticleCategory` | 分类 | SET_NULL，可空 |
| `tags` | M2M → `ArticleTag` | 标签 | 多对多 |
| `status` | CharField(20) | 状态 | 枚举，默认 `draft` |
| `view_count` | PositiveIntegerField | 阅读量 | 默认 0 |
| `knowledge_document` | FK → `Document` | 关联知识文档 | SET_NULL，可空 |
| `published_at` | DateTimeField | 发布时间 | 可空 |
| `created_at` / `updated_at` | DateTimeField | 时间戳 | auto |

- 状态枚举：`draft` / `published` / `archived` / `rejected`
- 索引：`workspace_key`、`slug`（unique）、`category`（FK）、排序 `-published_at, -created_at`

#### 2.4 `BlogComment` 评论

表名 `agent_api_blogcomment` ｜ 责任：博客 Agent

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `article` | FK → `BlogArticle` | 所属文章 | CASCADE |
| `author_name` | CharField(80) | 评论者 | 必填 |
| `content` | TextField | 内容 | 必填 |
| `is_approved` | BooleanField | 是否通过审核 | 默认 True |
| `created_at` | DateTimeField | 时间戳 | auto |

#### 2.5 `BlogAgentSession` 访客会话

表名 `agent_api_blogagentsession` ｜ 责任：博客 Agent

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `session_key` | CharField(64) | 会话标识 | unique |
| `visitor_label` | CharField(80) | 访客标签 | blank |
| `ip_hash` | CharField(64) | IP 哈希 | blank |
| `user_agent` | TextField | UA | blank |
| `is_blocked` | BooleanField | 是否封禁 | 默认 False |
| `created_at` / `updated_at` | DateTimeField | 时间戳 | auto |

#### 2.6 `BlogAgentMessage` 访客消息

表名 `agent_api_blogagentmessage` ｜ 责任：博客 Agent

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `session` | FK → `BlogAgentSession` | 所属会话 | CASCADE |
| `role` | CharField(16) | 角色 | 枚举 `user`/`agent` |
| `content` | TextField | 内容 | 必填 |
| `sources` | JSONField | 引用来源 | 默认 `[]` |
| `trace` | JSONField | 执行轨迹 | 默认 `[]` |
| `token_usage` | JSONField | token 用量 | 默认 `{}` |
| `created_at` | DateTimeField | 时间戳 | auto |

#### 2.7 `BlogAgentSecurityEvent` 访客安全事件

表名 `agent_api_blogagentsecurityevent` ｜ 责任：博客 Agent

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `session` | FK → `BlogAgentSession` | 所属会话 | SET_NULL，可空 |
| `question` | TextField | 触发问题 | 必填 |
| `reason` | CharField(160) | 拦截原因 | 必填 |
| `ip_hash` | CharField(64) | IP 哈希 | blank |
| `created_at` | DateTimeField | 时间戳 | auto |

---

### 对象 3：知识库（`models/knowledge.py`）

#### 3.1 `KnowledgeBase` 知识库

表名 `agent_api_knowledgebase` ｜ 责任：RAG 摄入

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `name` | CharField(120) | 名称 | 必填 |
| `workspace_key` | CharField(80) | 隔离键 | db_index |
| `description` | TextField | 描述 | blank |
| `category` | CharField(30) | 分类 | 枚举，默认 `other` |
| `tags` | JSONField | 标签列表 | 默认 `[]` |
| `is_archived` | BooleanField | 是否归档 | 默认 False |
| `sort_order` | IntegerField | 排序 | 默认 0 |
| `created_at` / `updated_at` | DateTimeField | 时间戳 | auto |

- 分类枚举：`tech_docs` / `product_docs` / `learning_notes` / `project_docs` / `other`
- 约束：`unique(workspace_key, name)`

#### 3.2 `Document` 文档

表名 `agent_api_document` ｜ 责任：RAG 摄入

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `knowledge_base` | FK → `KnowledgeBase` | 所属知识库 | CASCADE |
| `workspace_key` | CharField(80) | 隔离键 | db_index |
| `title` | CharField(180) | 标题 | 必填 |
| `source_file` | FileField | 源文件 | blank |
| `content_text` | TextField | 文本内容 | blank |
| `content_type` | CharField(120) | 内容类型 | blank |
| `status` | CharField(24) | 状态 | 枚举，默认 `pending` |
| `error_message` | TextField | 错误信息 | blank |
| `chunk_count` | PositiveIntegerField | 切片数 | 默认 0 |
| `created_at` / `updated_at` | DateTimeField | 时间戳 | auto |

- 状态枚举：`pending` / `processing` / `ready` / `failed`

#### 3.3 `DocumentChunk` 文本切片

表名 `agent_api_documentchunk` ｜ 责任：RAG 摄入

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `document` | FK → `Document` | 所属文档 | CASCADE |
| `knowledge_base` | FK → `KnowledgeBase` | 所属知识库 | CASCADE |
| `chunk_index` | PositiveIntegerField | 切片序号 | 必填 |
| `content` | TextField | 切片内容 | 必填 |
| `token_estimate` | PositiveIntegerField | 估算 token | 默认 0 |
| `metadata` | JSONField | 元数据 | 默认 `{}` |
| `created_at` | DateTimeField | 时间戳 | auto |

- 约束：`unique(document, chunk_index)`

#### 3.4 `EmbeddingRecord` 向量记录

表名 `agent_api_embeddingrecord` ｜ 责任：RAG 摄入

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `chunk` | OneToOne → `DocumentChunk` | 关联切片 | CASCADE |
| `model` | CharField(120) | embedding 模型 | 必填 |
| `vector` | JSONField | 向量 | 默认 `[]` |
| `vector_dimensions` | PositiveIntegerField | 维度 | 默认 0 |
| `created_at` | DateTimeField | 时间戳 | auto |

> 说明：`EmbeddingRecord.vector` 存 JSON，是 SQLite/开发环境的**降级路径**；生产环境的向量检索主路径在 pgvector 侧 `agent_api_vectorindex` 表（见下方 3.5）。

#### 3.5 `agent_api_vectorindex` pgvector 向量索引表（原生 SQL）

- 表名：`agent_api_vectorindex` ｜ 责任：RAG 摄入（检索主路径）
- 建表位置：`backend/apps/agent_api/services/vector_store.py` → `ensure_pgvector_schema()`
- ⚠️ **不走 Django ORM / migration**：由原生 SQL `CREATE TABLE IF NOT EXISTS` 建立，变更**不产生迁移文件**，须在附录 A 手动留痕。

| 字段 | 类型（PostgreSQL） | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `chunk_id` | bigint | 主键，兼外键 | PK + REFERENCES `agent_api_documentchunk(id)` ON DELETE CASCADE |
| `document_id` | bigint | 所属文档 | NOT NULL + REFERENCES `agent_api_document(id)` ON DELETE CASCADE |
| `knowledge_base_id` | bigint | 所属知识库 | NOT NULL + REFERENCES `agent_api_knowledgebase(id)` ON DELETE CASCADE |
| `workspace_key` | varchar(80) | 隔离键 | NOT NULL |
| `embedding` | vector | 向量 | NOT NULL（不定长，检索时按维度 cast） |
| `model` | varchar(120) | embedding 模型 | NOT NULL |
| `vector_dimensions` | integer | 维度 | NOT NULL |
| `metadata` | jsonb | 元数据 | NOT NULL，默认 `{}`（含 `source` / `chunk_index`） |
| `updated_at` | timestamptz | 更新时间 | NOT NULL，默认 `now()` |

- **支持维度**：`INDEXED_DIMENSIONS = (384, 1536, 3072)`，每个维度一个 HNSW 部分索引
- **索引**：
  - `agent_api_vectorindex_workspace_kb_idx`：B-tree 复合索引 `(workspace_key, knowledge_base_id)`
  - `agent_api_vectorindex_embedding_{384|1536|3072}_hnsw_idx`：HNSW，`((embedding::vector(N)) vector_cosine_ops)`，`WHERE vector_dimensions = N` 部分索引
- **写入方式**：`upsert_chunk_vector()` → `INSERT ... ON CONFLICT (chunk_id) DO UPDATE` 幂等 upsert
- **检索方式**：`search_pgvector()` → 余弦距离 `<=>` 排序，`score = GREATEST(0, 1 - distance)`；可过滤 `knowledge_base_id` / `workspace_key` / `d.status = 'ready'`
- **与 ORM 表的关系**：与 `EmbeddingRecord`（3.4）互补——前者是 PostgreSQL 生产主路径，后者是 JSON 降级路径

---

### 对象 4：对话与编排（`models/agent.py`）

#### 4.1 `Conversation` 会话

表名 `agent_api_conversation` ｜ 责任：Agent 编排

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `title` | CharField(160) | 标题 | blank |
| `workspace_key` | CharField(80) | 隔离键 | db_index |
| `owner_username` | CharField(150) | 所有者 | 默认 `anonymous`，db_index |
| `created_at` / `updated_at` | DateTimeField | 时间戳 | auto |

#### 4.2 `Message` 消息

表名 `agent_api_message` ｜ 责任：Agent 编排

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `conversation` | FK → `Conversation` | 所属会话 | CASCADE |
| `role` | CharField(16) | 角色 | 枚举 `user`/`agent` |
| `content` | TextField | 内容 | 必填 |
| `tool_calls` | JSONField | 工具调用 | 默认 `[]` |
| `sources` | JSONField | 引用来源 | 默认 `[]` |
| `trace` | JSONField | 执行轨迹 | 默认 `[]` |
| `token_usage` | JSONField | token 用量 | 默认 `{}` |
| `created_at` | DateTimeField | 时间戳 | auto |

#### 4.3 `AgentRun` 运行记录

表名 `agent_api_agentrun` ｜ 责任：Agent 编排

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `conversation` | FK → `Conversation` | 所属会话 | CASCADE |
| `workspace_key` | CharField(80) | 隔离键 | db_index |
| `input_message` | TextField | 输入 | 必填 |
| `route` | CharField(32) | 路由结果 | blank |
| `tool_calls` | JSONField | 工具调用 | 默认 `[]` |
| `sources` | JSONField | 引用来源 | 默认 `[]` |
| `trace` | JSONField | 执行轨迹 | 默认 `[]` |
| `token_usage` | JSONField | token 用量 | 默认 `{}` |
| `created_at` | DateTimeField | 时间戳 | auto |

---

### 对象 5：治理与工具（`models/governance.py`）

#### 5.1 `ApprovalRequest` 审批请求

表名 `agent_api_approvalrequest` ｜ 责任：治理层

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `action` | CharField(40) | 审批动作 | 枚举 |
| `workspace_key` | CharField(80) | 隔离键 | db_index |
| `title` | CharField(180) | 标题 | 必填 |
| `description` | TextField | 描述 | blank |
| `payload` | JSONField | 载荷 | 默认 `{}` |
| `status` | CharField(20) | 状态 | 枚举，默认 `pending` |
| `requester` | CharField(80) | 申请人 | blank |
| `reviewer` | CharField(80) | 审批人 | blank |
| `review_note` | TextField | 审批意见 | blank |
| `result` | TextField | 执行结果 | blank |
| `created_at` | DateTimeField | 创建时间 | auto |
| `reviewed_at` | DateTimeField | 审批时间 | 可空 |
| `executed_at` | DateTimeField | 执行时间 | 可空 |

- 动作枚举：`delete_document` / `delete_knowledge_base` / `delete_blog_article` / `publish_blog_article` / `execute_sql` / `execute_mcp_tool` / `external_deploy` / `send_email`
- 状态枚举：`pending` / `executed` / `rejected` / `failed`

#### 5.2 `MCPTool` 工具注册

表名 `agent_api_mcptool` ｜ 责任：治理层

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `name` | CharField(80) | 工具名 | unique |
| `workspace_key` | CharField(80) | 隔离键 | db_index |
| `display_name` | CharField(120) | 显示名 | 必填 |
| `description` | TextField | 描述 | blank |
| `category` | CharField(30) | 分类 | 枚举 |
| `permission_scope` | CharField(160) | 权限范围 | blank |
| `is_enabled` | BooleanField | 是否启用 | 默认 True |
| `requires_approval` | BooleanField | 是否需审批 | 默认 False |
| `config` | JSONField | 配置 | 默认 `{}` |
| `last_used_at` | DateTimeField | 最近使用 | 可空 |
| `call_count` | IntegerField | 调用次数 | 默认 0 |
| `success_count` | IntegerField | 成功次数 | 默认 0 |
| `health_status` | CharField(20) | 健康状态 | 枚举，默认 `unknown` |
| `last_health_check` | DateTimeField | 最近健康检查 | 可空 |
| `health_message` | TextField | 健康信息 | blank |
| `created_at` / `updated_at` | DateTimeField | 时间戳 | auto |

- 分类枚举：`system` / `filesystem` / `git` / `web` / `database`
- 健康枚举：`healthy` / `warning` / `error` / `unknown`

---

### 对象 6：评估与可观测（`models/evaluation.py`）

#### 6.1 `AgentObservation` 观测记录

表名 `agent_api_agentobservation` ｜ 责任：评估

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `conversation` | FK → `Conversation` | 关联会话 | SET_NULL，可空 |
| `agent_run` | FK → `AgentRun` | 关联运行 | SET_NULL，可空 |
| `input_message` | TextField | 输入 | 必填 |
| `workspace_key` | CharField(80) | 隔离键 | db_index |
| `answer` | TextField | 回答 | blank |
| `route` | CharField(40) | 路由结果 | blank |
| `selected_agent` | CharField(40) | 选中 Agent | blank |
| `trace` | JSONField | 轨迹 | 默认 `[]` |
| `tool_calls` | JSONField | 工具调用 | 默认 `[]` |
| `sources` | JSONField | 引用 | 默认 `[]` |
| `token_usage` | JSONField | token | 默认 `{}` |
| `latency_ms` | PositiveIntegerField | 延迟（ms） | 默认 0 |
| `tool_success_rate` | FloatField | 工具成功率 | 默认 1.0 |
| `status` | CharField(20) | 状态 | 枚举 `success`/`failed` |
| `failure_reason` | TextField | 失败原因 | blank |
| `langsmith_project` | CharField(120) | LangSmith 项目 | blank |
| `langsmith_run_id` | CharField(120) | LangSmith run | blank |
| `created_at` | DateTimeField | 时间戳 | auto |

#### 6.2 `EvaluationCase` 评估用例

表名 `agent_api_evaluationcase` ｜ 责任：评估

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `question` | TextField | 问题 | 必填 |
| `workspace_key` | CharField(80) | 隔离键 | db_index |
| `expected_answer` | TextField | 期望答案 | blank |
| `category` | CharField(30) | 分类 | 枚举 |
| `expected_route` | CharField(40) | 期望路由 | blank |
| `expected_agent` | CharField(40) | 期望 Agent | blank |
| `reference_keywords` | JSONField | 参考关键词 | 默认 `[]` |
| `is_active` | BooleanField | 是否启用 | 默认 True |
| `created_at` | DateTimeField | 时间戳 | auto |

- 分类枚举：`blog` / `knowledge` / `complex` / `jailbreak`

#### 6.3 `EvaluationRun` 评估运行

表名 `agent_api_evaluationrun` ｜ 责任：评估

| 字段 | 类型 | 说明 | 默认/约束 |
| --- | --- | --- | --- |
| `case` | FK → `EvaluationCase` | 关联用例 | CASCADE |
| `workspace_key` | CharField(80) | 隔离键 | db_index |
| `observation` | FK → `AgentObservation` | 关联观测 | SET_NULL，可空 |
| `answer` | TextField | 回答 | blank |
| `metrics` | JSONField | 指标 | 默认 `{}` |
| `passed` | BooleanField | 是否通过 | 默认 False |
| `created_at` | DateTimeField | 时间戳 | auto |

---

## 4. 关系与删除策略总览

| 主表 | 关联 | 目标 | 删除策略 | 说明 |
| --- | --- | --- | --- | --- |
| `UserProfile` | OneToOne | `auth.User` | CASCADE | 用户删则扩展删 |
| `BlogArticle` | FK | `ArticleCategory` | SET_NULL | 分类删文章保留 |
| `BlogArticle` | M2M | `ArticleTag` | — | 中间表自动清理 |
| `BlogArticle` | FK | `Document` | SET_NULL | 文档删文章保留 |
| `BlogComment` | FK | `BlogArticle` | CASCADE | 文章删评论删 |
| `Document` | FK | `KnowledgeBase` | CASCADE | 库删文档删 |
| `DocumentChunk` | FK | `Document` / `KnowledgeBase` | CASCADE | 文档删切片删 |
| `EmbeddingRecord` | OneToOne | `DocumentChunk` | CASCADE | 切片删向量删 |
| `Message` | FK | `Conversation` | CASCADE | 会话删消息删 |
| `AgentRun` | FK | `Conversation` | CASCADE | 会话删运行删 |
| `AgentObservation` | FK | `Conversation` / `AgentRun` | SET_NULL | 观测保留 |
| `EvaluationRun` | FK | `EvaluationCase` | CASCADE | 用例删运行删 |
| `EvaluationRun` | FK | `AgentObservation` | SET_NULL | 观测删运行保留 |

**约定**：主体数据用 `CASCADE`（会话→消息、文档→切片）；可独立存在的数据用 `SET_NULL`（文章→分类/文档）；`BlogAgent*` 访客数据用 `SET_NULL`（会话删安全事件保留）。

---

## 5. 索引约定（对应 lark「复合索引说明」）

| 表类型 | 索引 | 对应 lark |
| --- | --- | --- |
| 多租户业务表 | `workspace_key`（db_index） | 对应 `(pid)` |
| 多租户 + 私有表 | `workspace_key` + `owner_username` | 对应 `(pid, oid)` |
| 时序/对话表 | 外键 + 排序字段 | 对应 `(pid, oid, end)` |
| 检索表（chunk/embedding） | `document` FK + `unique(document, chunk_index)` | 对应区间索引 |
| 唯一约束 | `slug` / `name` / `session_key` / `unique(workspace_key, name)` | 对应静态表索引 |

**待补索引**（列入 `design-blueprint.md` 迭代路线图）：高频排序字段（`-created_at`、`-published_at`）建议补显式复合索引，当前依赖 Django 隐式索引。

---

## 附录 A：schema 变更日志

> 对应 lark 文档的「变更汇总（附录 A/B）」。每次 `makemigrations` 后在此登记，格式：`日期 | 类型 | 表 | 说明 | 迁移文件`。
> 变更类型：🆕 新增 ／ ❌ 删除 ／ ✏️ 字段变更 ／ 🔄 结构重构 ／ 📛 重命名。

| 日期 | 类型 | 表 / 字段 | 说明 | 迁移文件 |
| --- | --- | --- | --- | --- |
| 2026-09-23 | ✏️ 建档 | 全部 21 张 ORM 表 | 建立字段级参考手册，全量登记现有 schema | —（基于现状） |
| 2026-09-23 | 🆕 补录 | `agent_api_vectorindex`（pgvector 原生表） | 补录 `vector_store.py` 原生 SQL 建表，纳入 schema 覆盖（3.5 节） | —（原生 SQL，非 migration） |

### 待登记的已知问题（来自架构分析，尚未执行）

| 编号 | 类型 | 对象 | 说明 |
| --- | --- | --- | --- |
| T2 | ❌ 删除 | `models.py`（16KB 死代码） | 与 `models/` 包并存，包生效，`models.py` 为旧版死代码，待删除 |

---

## 附录 B：与 lark 数据库设计的差异

| 维度 | lark（MongoDB） | 当前系统（Django + PostgreSQL） |
| --- | --- | --- |
| 数据模型 | 文档型，无固定 schema | 关系型，强 schema + migration |
| 标准头部 | `pid/oid/start/end/update` 每表必带 | `workspace_key` + 时间戳，区间语义用具体字段 |
| 表命名 | `对象_类型_时间粒度` 自定义 | Django 自动 `app_label_model`，约定落在 model 类名 |
| 字段单位 | 字段名自带单位（kW/kWh） | 无物理量，用 `TextChoices`/`JSONField` 约束 |
| 索引 | 手写复合索引约定 | Django `db_index` + FK 自动索引 + `unique_together` |
| 变更追踪 | 附录 A/B 表+字段变更 | 本手册「附录 A 变更日志」+ migration 文件 |

**本质相通**：两者都是「**字段级字典 + 对象空间 + 标准约定 + 变更留痕**」。当前系统缺的是「字段级单一事实源」和「变更日志」这一层，本手册补齐。

---

*本手册随 schema 演进持续更新。初始化于 2026-09-23。字段以 `backend/apps/agent_api/models/*.py` 为最终实现。*
