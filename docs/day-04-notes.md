# Day 4: RAG 基础 + pgvector

第四天目标是实现知识库模块：文档上传、文本抽取、自动切分、embedding 记录、向量检索，并把检索结果接入 Agent 的最终回答流程。

## 学习目标

- 理解文档加载、文本切分、embedding、向量检索、引用来源。
- 理解 RAG 不是“文档里没有就不能答”，而是“检索结果作为上下文增强大模型回答”。
- 理解 pgvector 的定位：把业务数据和向量数据放在 PostgreSQL 中统一管理。

## 已完成

后端模型：

- `KnowledgeBase`：知识库。
- `Document`：上传的 Markdown、txt、PDF 文档。
- `DocumentChunk`：文档切分后的片段。
- `EmbeddingRecord`：chunk 对应的 embedding 向量记录。

后端能力：

- `GET /api/agent/knowledge-bases/`：知识库列表。
- `POST /api/agent/knowledge-bases/`：创建或更新知识库。
- `GET /api/agent/documents/`：文档列表。
- `POST /api/agent/documents/`：上传文档并同步处理。
- `POST /api/agent/documents/<id>/reindex/`：重新抽取、切分并生成 embedding。
- `POST /api/agent/knowledge-search/`：按 query 检索相关 chunk。

前端页面：

- 新增 `/knowledge` 知识库页面。
- 支持查看知识库。
- 支持上传 Markdown、txt、PDF。
- 支持查看文档处理状态和 chunk 数量。
- 支持手动输入 query 做检索测试。
- 支持对已有文档点击“重新处理”，用于切换 embedding 模型后重建索引。

Agent RAG 修复：

- 普通问题直接由 `gpt-4o-mini` 回答。
- 需要知识库或项目上下文的问题才调用 `knowledge_search` 工具。
- 工具检索结果只作为 prompt 上下文，不再作为最终答案边界。
- 最终回答仍由大模型生成。
- 如果上下文不足，大模型可以基于通用知识补充回答，并说明哪些是上下文信息、哪些是补充判断。
- 聊天页中每条 Agent 回复下方会用可折叠框展示检索到的相关内容。

## 当前向量实现

当前开发环境使用 SQLite，所以 Day4 先用 `JSONField` 保存向量，并在 Python 中计算相似度。

向量化模型使用百炼 / DashScope 的 OpenAI 兼容接口：

```text
BAILIAN_API_KEY=...
BAILIAN_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
BAILIAN_EMBEDDING_MODEL=text-embedding-v1
```

聊天模型和向量模型已经分离：

- `OPENAI_MODEL` 用于 Agent 对话。
- `BAILIAN_EMBEDDING_MODEL` 只用于知识库文档和 query 的向量化。

如果没有模型服务或 embedding 调用失败，会退回本地 hash embedding，保证测试和离线开发可以继续运行。

## 当前检索策略

当前检索已经从纯向量余弦相似度升级为 hybrid score：

```text
hybrid_score = vector_score * 0.72 + keyword_score * 0.28
```

其中：

- `vector_score` 来自 query embedding 和 chunk embedding 的余弦相似度。
- `keyword_score` 会参考完整 query 命中、标题命中、正文命中。
- 中文 query 会额外拆成 2-gram / 3-gram，缓解中文短句检索不稳定的问题。

## 未解决问题

当前检索相关性仍需后续完善。虽然已经加入百炼 `text-embedding-v1`、混合打分、中文 n-gram 关键词召回和文档重新处理功能，但整体效果还没有达到生产级 RAG。

后续优化方向：

- 上传文档后需要明确区分“旧 embedding”和“当前 embedding 模型”，避免混用不同维度或不同模型生成的向量。
- 增加 chunk 引用来源、页码、标题层级、原文位置。
- 增加 rerank 阶段，例如基于百炼 rerank 或 LLM judge 对候选 chunk 重排。
- 增加检索调试信息，在前端展示 vector score、keyword score、最终 hybrid score。
- 根据文档类型优化切分策略，Markdown 按标题切、PDF 按页码和段落切。
- 引入最小相关性阈值，避免低相关 chunk 被强行塞进 prompt。
- 后续切到 PostgreSQL + pgvector 后，把向量检索放到数据库侧执行。

这个问题已在 git 提交信息中标注为后续 TODO。

## 为什么暂时不是 pgvector

项目当前为了绕开 Docker 拉取镜像问题，已经切换到 SQLite。SQLite 不支持 pgvector，所以本日先完成 RAG 的工程闭环：

```text
上传文档 -> 抽取文本 -> 切分 chunk -> 写入 embedding -> 相似度检索 -> Agent prompt 上下文 -> 大模型回答
```

后续切回 PostgreSQL 后，可以把 `EmbeddingRecord.vector` 从 `JSONField` 替换为 pgvector 的 `VectorField`，并把 Python 余弦排序改成数据库侧向量查询。

## 后续 pgvector 改造路径

建议步骤：

1. 恢复 PostgreSQL + pgvector 服务。
2. 安装 `pgvector` Python 包。
3. 在 Django 中启用 pgvector extension。
4. 把 `EmbeddingRecord.vector` 改为 `VectorField(dimensions=1536)` 或对应 embedding 维度。
5. 用数据库查询替代 Python 循环打分。
6. 给检索结果增加引用来源、页码、chunk id 和重排逻辑。

## 今日验证

- 后端测试：`python manage.py test apps.agent_api`
- 迁移检查：`python manage.py makemigrations --check --dry-run`
- 前端构建：`npm run build`

以上验证均已通过。
