# Day 5: Agentic RAG，而不是普通 RAG

第五天目标是把 Day4 的“检索后回答”升级为 Agentic RAG：让 Agent 自己判断是否需要检索、检索结果是否相关、是否需要改写问题，并在最终答案中给出引用来源。

## 学习目标

- 理解普通 RAG 和 Agentic RAG 的区别。
- 掌握 LangGraph 中多节点 RAG 工作流的组织方式。
- 理解 query analyzer、retriever、document grader、query rewrite、answer generation、citation 的职责。

## 当前图工作流

代码位置：`agent/simple_agent.py`

```text
query_analyzer
  -> retrieve
  -> grade_documents
  -> rewrite_query
  -> generate
  -> cite_sources
  -> END
```

条件流：

```text
用户问题
  -> query_analyzer
    -> direct: generate
    -> retrieve: retrieve
  -> grade_documents
    -> 如果来源不足且还有重写次数: rewrite_query -> retrieve
    -> 否则: generate
  -> cite_sources
```

## 节点说明

- `query_analyzer`：判断问题是否需要知识库 / 文档 / 工具上下文。
- `retrieve`：执行知识库检索、计算器或用户资料工具。
- `grade_documents`：根据最高相似度判断检索结果是否足够可靠。
- `rewrite_query`：当检索结果不足时改写 query，再检索一次。
- `generate`：直接回答、基于来源回答，或在无来源时说明“不知道 / 当前资料不足”。
- `cite_sources`：整理引用来源，让后端和前端都能展示依据。

## 已完成

后端：

- Agent 图升级为 Agentic RAG。
- 回答结果新增 `sources` 字段。
- `Message` 和 `AgentRun` 持久化 `sources`。
- `POST /api/agent/chat/` 返回结构化引用来源。
- 历史消息接口返回 `sources`，刷新后仍能看到引用。

前端：

- 聊天页答案下方展示“引用来源”。
- 每个来源展示文档标题、chunk index、相似度、片段内容。
- 原有工具调用折叠框继续保留，用于查看完整检索上下文。

企业亮点：

- 每个回答可以看到来源，不再是黑盒回答。
- 检索不到明确来源时，Agent 会说明当前知识库资料不足。
- 检索结果不足时，Agent 会尝试改写 query 后再次检索。

## 与普通 RAG 的区别

普通 RAG 更像固定流水线：

```text
用户问题 -> 检索 -> 拼 prompt -> 回答
```

Agentic RAG 多了决策能力：

```text
用户问题 -> 判断是否检索 -> 检索 -> 评估文档 -> 必要时改写问题 -> 生成答案 -> 引用来源
```

它更适合企业知识库场景，因为企业问题经常存在表述不清、资料不足、检索噪声和引用要求。

## 当前限制

- 文档评分目前主要基于 hybrid score 阈值，还不是 LLM grader。
- query rewrite 只做一次，后续可以增加多轮改写和失败原因记录。
- 引用来源目前是 chunk 级别，还没有 PDF 页码、标题层级和原文链接。
- 相关性仍需 rerank 模型或 LLM judge 继续提升。

## 后续优化

- 增加 `vector_score`、`keyword_score`、`hybrid_score` 的调试展示。
- 接入 rerank 模型重新排序候选 chunk。
- Markdown 按标题切分，PDF 按页码和段落切分。
- 引入最小相关性阈值，低于阈值时明确回答“不知道”。
- 将 SQLite JSON 向量替换为 PostgreSQL + pgvector。

## 今日验证

- 后端测试：`python manage.py test apps.agent_api`
- 前端构建：`npm run build`
