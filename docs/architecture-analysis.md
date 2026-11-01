# 全项目架构分析报告

> 历史快照：本报告形成于 V2 改造前，以下文件数量、迁移数、测试覆盖及目录判断不代表当前仓库。尤其“后端没有测试”和“根 `agent/` 仍有第二套源码”的描述已失效。当前设计与发布阻断项请看 [Blog 设计文档 V2.0](Blog设计文档V2.0.md)、[评测与测试升级方案 V2.0](评测与测试升级方案V2.0.md) 和 [缺陷跟踪表 V2.0](缺陷跟踪表V2.0.md)。本报告保留供比较改造前后的决策，不作为面试或部署现状证据。

> 分析对象：`Blog-fixed-20260727/Blog`（Git 远端 `git@github.com:yuanbin2/IPBS.git`）
> 分析方式：源码通读 + 交叉验证（含参数级核对），非基于文档推断。

---

## 1. 一句话定位

**企业知识智能体平台 + 个人博客智能体**，是一个以「Agentic RAG + 多智能体协作 + Human-in-the-loop」为核心的工程化学习项目。它的设计重心不在模型能力，而在**工程骨架的完整性**：权限、审批、可观测、降级、部署全都真实落地了。

---

## 2. 规模盘点

| 维度 | 数值 |
| --- | --- |
| 后端 Python（`backend/` + `agent/`） | ≈ 16,990 行 |
| 前端 Vue / TS（`frontend/src`） | ≈ 7,267 行 |
| 业务 app 数量 | **1 个**（`backend/apps/agent_api/`） |
| 数据库迁移 | 26 个 |
| Celery 异步任务 | **1 个**（`tasks.py:9` `@shared_task` → `ingest_document_task`） |
| 顶层目录 | 10 个（含 4 个 desktop 相关目录，见第 11 节） |

规模不大，但纵向切得很深 —— 一个 app 里塞下了用户/RBAC、博客、知识库、向量、对话、审批、工具注册、可观测、评估九块领域。

---

## 3. 五层架构

```
┌──────────────────────────────────────────────────────────────┐
│ 接入层   Vue3 + Vite + TS + Pinia + Element Plus             │
│          + Electron 壳（desktop/）+ Edge App 启动器          │
├──────────────────────────────────────────────────────────────┤
│ 接口层   Django + DRF + ASGI                                 │
│          /api/agent/* · JWT · RBAC · workspace 隔离          │
├──────────────────────────────────────────────────────────────┤
│ 编排层   MultiAgentSupervisor (agent/multi_agent.py)         │
│          纯关键词优先级瀑布 —— 不是 LLM 分类器                │
├──────────────────────────────────────────────────────────────┤
│ 智能层   SimpleToolCallingAgent (agent/simple_agent.py)      │
│          真正的 LangGraph StateGraph + 工具调用 + 纠错回环    │
├──────────────────────────────────────────────────────────────┤
│ 数据层   PostgreSQL + pgvector(HNSW) · Redis · RabbitMQ      │
│          Celery worker / beat                                │
└──────────────────────────────────────────────────────────────┘
```

一个关键认知：**编排层和智能层是两个独立组件，不是一个**。`multi_agent.py` 负责「选谁来干」，`simple_agent.py` 负责「具体怎么干」。

---

## 4. 一次请求的完整穿透

以 `POST /api/agent/chat/` 为例：

```
1. JWT 鉴权 → 解析 user + workspace_key
2. detect_sensitive_input()          ← 安全检查，前置，先于路由
     命中 → 直接转 admin_approval_agent（防止关键词被下方分支吞掉）
3. supervisor_routing.decide()        ← 规则优先级分发，首个命中即返回
4. 命中子 Agent → 执行
     rag_agent  → SimpleToolCallingAgent 跑 LangGraph
     blog_agent → 公开博客检索
     mcp_tool   → 工具注册表（带权限/审批开关）
     sql_agent  → 受限统计查询
5. generate → END（检索来源随状态和响应保留）
6. 输出脱敏 → 落库 Conversation / Message / AgentRun → 审计日志
```

**设计要点**：第 2 步的「安全检查前置」是一个正确的决定。注释里写得很明白 —— 「删除知识库」这类请求必须不能被下面的检索关键词抢走，否则一个破坏性操作会被当成普通查询处理。治理优先级 > 业务路由。

---

## 5. 编排层：Supervisor 路由详解

`agent/supervisor_routing.py` 的 `decide()` 是**规则优先级分发**，自上而下第一个命中就 `return`：

| 序 | Agent | 触发关键词 | 置信度 |
| --- | --- | --- | --- |
| 1 | `admin_approval_agent` | 审批 / 发布审核 / 删除 / 敏感 / 权限 / 管理员 / admin | 0.88 |
| 2 | `mcp_tool_agent` | `is_mcp_request()` 结构化判定 | 0.94 |
| 3 | `blog_agent`（System Facts） | `is_system_stack_question()` | 0.99 |
| 4 | `rag_agent`（Private Knowledge） | 简历 / 我的文档 / 上传的文档 / 知识库文档 / 附件 | 0.98 |
| 5 | `rag_agent`（Private Knowledge） | 哪个学校 / 毕业院校 / 任职单位 / 来自哪里 | 0.96 |
| 6 | `rag_agent`（Private Knowledge） | 散射成像 / 散斑 等双语技术主题 | 0.95 |
| 7 | `rag_agent`（Private Knowledge） | 短技术词（2–24 字 + 成像/算法/模型/技术…后缀） | 0.90 |
| 8 | `rag_agent`（Private Knowledge） | 数据库 / 知识库 / 查找 / 检索 / 搜索 / 依据 | 0.91 |
| 9 | `mcp_tool_agent` | mcp / tool / 工具 / git / 仓库 / 本地文件 | 0.86 |
| 10 | `review_agent` | 检查 / 审查 / review / 幻觉 / 引用 | 0.82 |
| 11 | `sql_analysis_agent` | 统计 / 多少 / 数量 / 文章数 / sql / 数据分析 | 0.86 |
| 12 | `blog_agent` | 博客 / 个人 / 项目经历 / 关于我 | 0.84 |
| 13 | `rag_agent`（Writing） | 写 / 润色 / 总结 / 提纲 / 标题 / 摘要 | 0.78 |
| 14 | `rag_agent` | 正则算式 或 兜底工具类关键词 | 0.90 |
| 15 | `rag_agent`（General 兜底） | 其他一切 | 0.62 |

### 优点

- **无模型 token 成本**：路由不调模型，主要是字符串规则；路由本身耗时尚未做同条件函数/图对照。
- **优先级顺序有真实设计意图**：治理 → 工具 → 事实 → 私有知识 → 通用检索。注意 4–8 级全是 `rag_agent`，但被拆成 5 个入口，每个带不同置信度 —— 这是在用关键词「伪造」细粒度意图识别。
- **置信度是静态标签**：例如技术栈事实为 0.99、兜底为 0.62；没有概率校准，不应据此判断回答可信程度。

### 隐患

- **顺序耦合极强**：第 8 级含「搜索」「网络」「检索」，第 9 级含「工具」「文件搜索」。一旦上游新增关键词，极易把下游分支永久屏蔽（**饿死**）。这类 bug 不报错，只是路由静默走错，非常难发现。
- **中文分词未做**：直接 `in` 子串匹配。像「搜索」这样的高频词，会误伤「我想搜索一下我的博客」这类本应进 `blog_agent` 的请求。
- **置信度是硬编码常量，不是真实概率**：路由由规则顺序决定，当前数值不能作为可靠性评分或排序依据。

---

## 6. 智能层：LangGraph 状态图

`agent/simple_agent.py` 中的有限 `StateGraph`：

```
query_analyzer ──(需检索)──> retrieve ──> grade_documents ──(生成)──> generate ──> END
      │                                          │
      └──(普通问题直接回答)──────────────────────────────────────────> generate
                                                 │
                                             (低相关且未改写)
                                                 ▼
                                          rewrite_query ──(最多 1 次)──> retrieve
```

节点清单（`add_node` 共 5 个）：
`query_analyzer` / `retrieve` / `grade_documents` / `rewrite_query` / `generate`。
原 `cite_sources` 只追加 trace，未生成引用，现已移除；来源由检索状态保留并返回。

边结构：`query_analyzer` 分流至 `retrieve` 或 `generate`；
`retrieve → grade_documents`；低相关时 `grade_documents → rewrite_query → retrieve` 至多一次；其余路径 `generate → END`。

`max_rewrites=1` 限制低相关检索改写回环次数；该上限控制调用次数，但 I-001 尚未证明复杂检索链对人工复核样本的收益。图的保留理由和后续简化条件见 [I-007 ADR](I-007-LangGraph工作流决策.md)。

---

## 7. RAG 完整链路

实现集中在 `backend/apps/agent_api/services/rag.py`。

### 切分（`rag.py:32-136`）

```python
CHUNK_SIZE = 900        # 900
CHUNK_OVERLAP = 140     # 140
```

策略是**三段式**：
1. 先按空行切段落（`re.split(r"\n{2,}")`）
2. 段落超长 → `split_long_text()` 按 `chunk_size` 硬切，步进 `end - overlap` 保留重叠窗口
3. 段落累积到接近上限再落块 → 保留段落语义边界

比无脑定长切分质量高，且完全自研、无第三方 splitter 依赖。

### 混合打分（`rag.py:34-35`）

```python
VECTOR_SCORE_WEIGHT = 0.72
KEYWORD_SCORE_WEIGHT = 0.28
```

**0.72 向量 + 0.28 关键词**。检索路径为：
pgvector 侧 `vector_cosine_ops` Top-K（`services/vector_store.py:83`，HNSW 索引）
→ 关键词分数叠加重排
→ 邻域 chunk 扩展（权重 `0.97^distance`，把相邻块按距离衰减召回）
→ 多样性重排

### 三级降级路径（工程亮点）

| 组件 | 正常路径 | 降级路径 |
| --- | --- | --- |
| Embedding | 远程 embedding API | 本地 `sha256` 哈希 → 384 维伪向量 |
| 向量检索 | pgvector HNSW | Django JSON 字段全表扫描 + `cosine_similarity()`（`rag.py:272`） |
| 生成 | 真实 LLM | `_fallback_chat` 本地兜底回答 |

这意味着**没配任何 API Key 的情况下，整个系统仍能跑通并给出可用回答**。README 里也是这么承诺的。这是很多人做 Demo 时忽略、但工程上极其重要的能力。

`RAG_VECTOR_BACKEND=django` 可手动切回兼容检索（见 README 与 `docker-compose.yml:37`）。

---

## 8. 安全与治理

| 能力 | 落点 |
| --- | --- |
| 登录注册 | DRF 认证体系 |
| RBAC | 角色/权限模型 + DRF 权限类 |
| workspace 隔离 | 所有查询按 `workspace_key` 过滤 |
| Prompt injection 拦截 | `detect_sensitive_input()`，**前置**于 Supervisor 路由 |
| 输出脱敏 | 生成后处理 |
| 安全审计 | 审计日志模型 |
| Human-in-the-loop | 删除/发布/MCP 调用 → 审批队列 |
| 工具权限 | 工具注册表：启用开关 / 权限范围 / 审批开关 |

审批覆盖的真实动作：删除、发布、MCP 工具调用。**高危操作全部强制走人工** —— 这是企业级 Agent 的必要条件。

---

## 9. 部署：四条并行路径

| # | 路径 | 入口 | 基础设施 | 使用的 agent 源码 |
| --- | --- | --- | --- | --- |
| ① | 本地一键 | `start.sh` / `start.bat` | SQLite + LocMemCache + Celery eager | `backend/agent/` |
| ② | Docker Compose | `docker-compose.yml` | Nginx + gunicorn + pgvector:pg16 + Redis + RabbitMQ + Celery worker/beat | **`backend/agent/`**（`backend/Dockerfile`） |
| ③ | Railway | 根 `Dockerfile` + `railway.json` | 仅后端 gunicorn | **根 `agent/`**（根 `Dockerfile`） |
| ④ | Cloudflare Pages | `frontend/dist` | 静态（含 `_headers` / `_redirects` / `_routes.json`） | — |

本地模式靠 `BLOG_LOCAL_MODE=true` 切换，不依赖任何外部中间件，`start.sh:29` 明确设置。

---

## 10. 工程质量现状

**有的**：
- GitHub Actions CI（`.github/workflows/ci.yml`）：测试 + 前端构建 + Compose 校验
- `deploy/backend/entrypoint.sh` 支持 `RUN_MIGRATIONS` / `COLLECT_STATIC` 开关，worker 容器正确关掉了这两项
- Compose 里所有服务都配了 healthcheck 和 `depends_on: condition: service_healthy`，依赖顺序严谨
- `docs/` 下有 8 篇文档，含架构图、API 文档、评估报告、部署说明

**缺的**：
- 后端测试文件：`backend/` 下未发现 `test*.py`
- 无 `admin.py`
- 无 pre-commit 配置落地

---

## 11. 技术债清单（按严重度排序）

### 🔴 高：`agent/` 与 `backend/agent/` 双份源码且已分叉

- `multi_agent.py` 两份 **md5 不同**（根版本联网关键词更全）
- `simple_agent.py` / `mcp_tools.py` 两份一致
- **后果**：② Docker 部署跑 `backend/agent/`，③ Railway 部署跑根 `agent/` —— **同一份 API，两套编排逻辑**。改了一处忘了另一处，线上行为会不一致，且极难排查。
- **修复**：保留一份（建议根 `agent/` 作为唯一源），另一处改为构建期复制或 Python 包引用。

### 🟠 中：`models.py` 与 `models/` 包并存

`backend/apps/agent_api/` 下同时存在 `models.py`（约 16KB）和 `models/` 包。Python 的导入优先级会让**包生效**，`models.py` 成为死代码，且字段定义更旧。
**后果**：读代码的人极容易改错文件，改了不生效。
**修复**：直接删除 `models.py`。

### 🟠 中：4 个桌面端目录职责重叠

| 目录 | 真实身份 | 状态 |
| --- | --- | --- |
| `desktop/` | 真 Electron + electron-vite 工程 | 有源码，但有 main.ts / main.js 双份 |
| `app-desktop/` | Edge App 启动器（`.bat` / `.ps1`） | 有源码 |
| `desktop-app/` | — | **空壳**，只有 node_modules |
| `app-desktop/` 内多套启动脚本 | | 职责重叠 |

另发现 `desktop/` 中 preload 暴露的是 `window.api`，但 `App.vue` 读取 `window.electronAPI` —— **键名不匹配**，渲染进程拿不到值。
**修复**：删 `desktop-app/`；统一 preload 暴露键名。

### 🟠 中：Nginx 流式输出配置缺失

`deploy/nginx/default.conf` 只设了 `proxy_http_version 1.1` + `read_timeout 180s`，**缺 `proxy_buffering off`**。
**后果**：SSE 端点 `/api/agent/chat/stream/` 可能被 Nginx 缓冲聚合，前端「打字机」效果退化为一次性整段返回。
**修复**：在该 location 加 `proxy_buffering off;` 和 `proxy_cache off;`。

### 🟡 低：Celery Beat 空转

全项目只有 1 个 Celery task（`ingest_document_task`），却起了 worker + beat 两个容器，而 **beat 没有任何 schedule 配置**。
**修复**：删掉 `celery_beat` 服务，或补上定时任务（如过期会话清理、向量重建）。

### 🟡 低：`celery_beat` 容器环境变量缺失

`docker-compose.yml:85-90` 里 beat 注入了 `REDIS_URL` 和 `RABBITMQ_URL`，但**未注入 `REDIS_CACHE_URL`**；另 `CELERY_BROKER_URL` 指向 RabbitMQ 而部分配置可能仍读 Redis。
**修复**：对齐三个 Celery 容器的环境变量。

### 🟡 低：`SecurityView.vue` 未挂路由

前端存在安全管理页面文件，但路由表里没有对应入口 —— 功能做了但用户访问不到。

---

## 12. 改进建议

### 短期（性价比最高，建议优先）

1. **合并 `agent/` 双份源码** —— 这是唯一会导致「线上行为不一致」的问题，优先级最高。
2. **删掉 `models.py` 死代码** —— 一行删除，消除最大的阅读陷阱。
3. **Nginx 补 `proxy_buffering off`** —— 直接影响核心体验（流式输出）。
4. **删 `desktop-app/` 空壳目录** —— 减少认知负担。

### 中期

5. **Supervisor 路由加单测** —— 给每个分支构造 3–5 条典型输入，断言路由结果。当前 15 级关键词瀑布完全无测试保护，改动风险极高。
6. **把关键词瀑布改为「打分 + 阈值」** —— 现在是硬优先级，任一分支命中即独占。改成各分支独立打分取最高分，可消除「饿死」问题。
7. **补后端单测** —— CI 已就绪，但无测试可跑。

### 长期

8. **引入轻量意图分类器（可选）** —— 关键词瀑布的维护成本会随分支数线性增长。当分支超过 20 个时，改用小模型分类 + 关键词兜底会更稳。当前规模（15 级）用瀑布仍合理。

---

## 13. 可以直接讲的亮点（面试/简历）

1. **Agentic RAG 的自我纠错回环** —— 带次数上限的 `rewrite → retrieve` 回环，工程上封顶防失控。
2. **三级降级设计** —— embedding / 向量库 / LLM 全链路可降级，无 Key 可跑。这是区分「Demo」和「工程」的分水岭。
3. **治理优先级前置** —— 安全检查和审批判定先于业务路由，破坏性操作无法被关键词误吞。
4. **混合检索打分** —— 0.72 向量 + 0.28 关键词 + 邻域扩展 + 多样性重排，四层召回优化，非简单向量检索。
5. **Human-in-the-loop 真实落地** —— 覆盖删除、发布、MCP 调用，带审批队列与工具级权限开关。
6. **四条部署路径** —— 从零依赖本地启动到完整 Compose 生产栈，兼顾可演示性和可部署性。

---

## 14. 总结

这个项目的**架构选择是合理的**：分层清晰、职责边界明确、降级和治理都真实落地，五个技术亮点都站得住。

它的主要问题**不在设计，而在「施工收尾」**：双份源码、死代码、空壳目录、配置遗漏 —— 全是「做完没清理」留下的问题，而不是「想错了」。这类问题恰好说明它是边做边演进的项目，也恰好是可以低成本修复的。

**如果只做一件事**：合并 `agent/` 双份源码。它是唯一一个会让「本地跑得好、线上跑不对」的隐患。

---

*报告生成时间：2026-09-23*
*分析基于源码通读，关键参数（切分尺寸、打分权重、索引类型、任务数量）均已逐项核对。*
