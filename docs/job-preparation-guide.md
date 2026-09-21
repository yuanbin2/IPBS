# 全栈工程师岗位准备与项目学习指南

这份指南把项目改造成一套可学习、可演示、可用于面试讲解的全栈案例。目标岗位要求可以归纳为：Python 后端、Vue 前端、数据库与架构、DevOps、AI Agent 加分项。

## 1. 岗位要求与项目证据

| 岗位能力 | 项目中的实现 | 面试时要能讲清楚 |
| --- | --- | --- |
| Python / Django / REST API | `backend/config`、`backend/apps/agent_api` | 请求生命周期、DRF APIView、状态码、异常处理、鉴权 |
| async / Celery / RabbitMQ | `config/celery.py`、Compose worker/beat | Web 请求与后台任务的边界、幂等、重试、消息积压 |
| JWT / CSRF / RBAC | 登录 API、角色与 workspace、安全审计 | Cookie 与 Token 风险、最小权限、租户隔离 |
| Vue 3 / TypeScript / Pinia / Router / Vite | `frontend/src` | Composition API、响应式、状态归属、路由守卫、构建 |
| PostgreSQL / 数据建模 | Django models 与 migrations | 索引、事务、N+1、读写分离的适用条件 |
| Redis / NoSQL | 缓存与 Celery result backend | 缓存穿透、雪崩、一致性和过期策略 |
| 微服务与单体架构 | 当前为模块化单体，Agent 独立目录 | 为什么先选模块化单体，何时拆服务 |
| Docker / Compose / Nginx | `docker-compose.yml`、`deploy` | 网络、卷、健康检查、反向代理、静态资源 |
| CI/CD | `.github/workflows/ci.yml` | 测试、构建、Compose 校验、发布门禁 |
| 监控 | AgentObservation、评估页 | latency、error rate、tool success、token cost |
| AI Agent / RAG / MCP / HITL | `agent` 与 agent_api | 路由、检索、重写、引用、工具权限、人审、降级 |

尚未真正实现、不能在面试中夸大的能力：Kubernetes、Prometheus/Grafana/ELK、真实云资源、真实高并发压测、真实外网搜索、数据库读写分离与分库分表。可以说明设计方案，但不要声称已有生产经验。

## 2. 从零搭建顺序

### 阶段 0：环境

安装 Git、Python 3.12、Node 20、Docker Desktop。复制环境变量：

```powershell
Copy-Item .env.example .env
```

任何真实密钥只写进 `.env`，不要提交。先阅读 `.env.example`，理解数据库、Redis、Django 和模型服务各配置项。

### 阶段 1：先做最小后端

```powershell
Set-Location backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

先自己重写一个 `/api/health/`，再做文章 CRUD。学习顺序：URL 路由 → View → ORM Model → Migration → Serializer/响应 → TestCase。每增加一个接口，都写成功、非法输入、无权限、资源不存在四类测试。

### 阶段 2：搭建 Vue 前端

```powershell
Set-Location frontend
npm ci
npm run dev
```

按 `main.ts → App.vue → router → view → store` 阅读。先手写登录页和文章列表，再接 Agent Chat。重点观察 loading、error、empty 三种 UI 状态，以及 Token、用户资料、会话分别应该放在哪里。

### 阶段 3：数据库和异步任务

先用 SQLite 理解 ORM，再切 PostgreSQL。画出 KnowledgeBase、Document、DocumentChunk、Conversation、Message 的 ER 图。给常用筛选字段加索引，用 `EXPLAIN` 判断索引是否命中。

把“上传文档后的解析和切块”作为 Celery 任务：API 只创建 pending 记录并返回任务 ID；worker 处理后更新 ready/failed。必须考虑重复投递、重试次数、失败原因和任务幂等。

### 阶段 4：从普通检索到 Agentic RAG

按以下顺序实现，不要一开始就做多 Agent：

1. 文档读取、切块、embedding、入库。
2. query → top-k 检索 → context → LLM。
3. 返回结构化 sources，确保答案引用能对应原文。
4. 加 query rewrite 和 relevance grading。
5. 加本地降级：模型不可用时仍返回检索依据，不伪造联网结果。
6. 最后加入 Supervisor、多专业 Agent、MCP 工具和 HITL。

当前 Agent 请求链路：

```text
POST /api/agent/chat
  -> 输入校验与安全审计
  -> Supervisor（治理路由优先）
  -> 专业 Agent
     -> RAG: analyze -> retrieve -> grade -> rewrite? -> generate -> cite
     -> SQL: 仅聚合白名单
     -> MCP: 注册表 -> 启用/权限检查 -> 执行
     -> Approval: 只建审批，不直接做高风险动作
  -> 输出脱敏
  -> Message + AgentRun + Observation 持久化
  -> API 响应
```

调试时依次检查：输入是什么、Supervisor 为什么路由、调用了什么工具、来源是否相关、是否触发降级、返回的 route 与 supervisor 是否一致、观测记录是否落库。

### 阶段 5：容器、CI 与部署

```powershell
docker compose config
docker compose up -d --build
docker compose ps
```

理解每个 service 的 image/build、environment、depends_on、healthcheck、volume 和 network。然后阅读 CI：后端测试、前端类型检查与构建、Compose 配置校验。下一步练习是在测试通过后构建镜像并推送镜像仓库；Kubernetes 放在完成 Compose 后学习。

## 3. 推荐的 8 周学习路线

| 周 | 学习重点 | 必须产出 |
| --- | --- | --- |
| 1 | Python、类型、异常、pytest、HTTP | 手写 API 与 20 个测试 |
| 2 | Django/DRF、ORM、鉴权、安全 | 文章 CRUD、登录、RBAC |
| 3 | PostgreSQL、索引、事务、Redis | ER 图、EXPLAIN、缓存实验 |
| 4 | Vue 3、TS、Pinia、Router | 登录、博客、管理台 |
| 5 | Celery、asyncio、可靠任务 | 异步文档处理与失败重试 |
| 6 | RAG、LangGraph、评估 | 可引用 RAG 与离线评估集 |
| 7 | Docker、Nginx、CI/CD、Linux | 一键启动与 CI 全绿 |
| 8 | 监控、压测、系统设计、复盘 | 压测报告、架构图、演示视频 |

每天使用“读 30 分钟 → 关掉源码重写 60 分钟 → 写测试 30 分钟 → 口述 15 分钟”的循环。判断学会的标准不是看懂，而是能从空目录复现、定位一个故障、说明一种取舍。

## 4. 完整学习清单

- Python：数据模型、装饰器、生成器、上下文管理器、类型标注、异常、asyncio、GIL、进程/线程。
- Web：HTTP、REST、状态码、Cookie/Session/JWT、CORS、CSRF、OAuth2、限流、幂等。
- Django/DRF：ORM、migration、middleware、APIView、权限、事务、分页、过滤、测试。
- Vue：Composition API、响应式原理、组件通信、生命周期、Pinia、Router、TypeScript、Vite、性能与 SEO；了解 Nuxt/SSR/PWA。
- 数据库：范式、索引/B+Tree、事务/ACID/MVCC、隔离级别、锁、慢查询、连接池、复制、分区、分库分表。
- Redis/MQ：数据结构、缓存模式、分布式锁、持久化、Celery、确认/重试/死信/幂等；了解 RabbitMQ。
- 架构：模块化单体、微服务、DDD 边界、API 网关、熔断、降级、限流、一致性。
- Linux/网络：进程、文件权限、日志、Shell、TCP/IP、DNS、HTTP/TLS、CPU/内存/磁盘/网络瓶颈。
- DevOps：Docker、Compose、Nginx、GitHub Actions、制品与回滚；再学 Kubernetes、云服务、Prometheus/Grafana、ELK/OpenSearch。
- Agent：prompt、tool calling、state graph、RAG、embedding、chunking、rerank、引用、幻觉、评估、MCP、HITL、权限与 prompt injection。

## 5. 面试题与回答要点

1. 为什么这个项目使用模块化单体而不是微服务？ 早期规模下事务、调试和部署成本更低；以 app 和 Agent 接口保持边界，出现独立扩缩容或团队边界后再拆。
2. Django 一次请求如何到达数据库再返回？ 讲 URL、middleware、view、ORM、connection、response，并指出事务边界。
3. `select_related` 与 `prefetch_related` 区别？ 前者 SQL join 适合单值关系，后者额外查询后在内存拼装，适合多值关系。
4. JWT、Session 各有什么风险？ JWT 易撤销困难且要防泄漏；Cookie Session 要防 CSRF；都需 TLS、过期、轮换和最小权限。
5. Celery 如何避免一个文档被重复处理？ 业务幂等键、状态机、事务提交后投递、任务重试限制和可观测失败状态。
6. PostgreSQL 复合索引字段顺序如何选？ 依据过滤选择性、等值/范围条件、排序和最左前缀，并用真实查询计划验证。
7. Redis 缓存与数据库不一致怎么办？ 常用 cache-aside，先更新库再失效缓存；说明并发窗口、延迟双删和过期兜底。
8. Vue 的 `ref` 与 `reactive` 有何差异？ 值包装和对象代理、解构丢失响应性、模板自动解包。
9. Pinia 中什么状态不该全局化？ 页面短期表单与局部 loading；只共享跨组件/跨路由业务状态。
10. Docker volume 和 bind mount 的区别？ volume 由 Docker 管理，适合持久数据；bind 绑定宿主路径，开发配置直观但环境耦合。
11. readiness 与 liveness 有何区别？ 前者决定是否接流量，后者决定是否重启；依赖短暂失败通常不应导致重启风暴。
12. Agent 为什么不能根据 trace 文本决定下一节点？ trace 是可观测输出，不是稳定协议；应使用类型明确的结构化 state。
13. RAG 没检索到资料怎么办？ 重写一次、调整检索策略；仍无依据就明确不知道，不能让模型伪造来源。
14. 如何评价 RAG？ retrieval recall/precision、faithfulness、answer relevance、citation correctness、latency、cost，并维护回归集。
15. 如何防 prompt injection？ 输入检测只是辅助；核心是工具最小权限、参数校验、数据与指令分离、审批、输出脱敏和审计。
16. Supervisor 路由冲突怎么解决？ 用优先级：安全/审批 > 明确工具 > 业务专长 > 默认；为冲突语句写回归测试。
17. 为什么 SQL Agent 只提供聚合白名单？ 避免任意 SQL、结构泄漏和跨租户访问；查询还要绑定 workspace。
18. 如何支持高并发？ 先测量；无状态 Web 横向扩展、连接池、缓存、队列削峰、慢查询优化、静态资源 CDN，并定义 p95/p99。
19. 怎样做到零停机发布？ 向后兼容 migration、滚动发布、readiness、流量切换、可回滚镜像和数据库变更策略。
20. 这个项目最真实的不足是什么？ 目前主要是学习/演示系统，缺少生产流量、真实 K8s/云部署和系统压测；说明下一步验证计划。

### 场景追问

- “删除知识库中的旧资料”同时命中删除和知识库，该去哪个 Agent？先 Approval；治理优先。
- 模型服务超时但检索成功，页面显示什么？显示真实本地来源和降级说明，不能假装完成生成或联网。
- Worker 执行成功但更新状态失败怎么办？任务必须可重试且幂等，保存外部执行标识，必要时对账补偿。
- 某租户传入另一个 conversation ID 怎么办？所有查询都同时约束主键和 workspace，返回 404/403 并写审计。
- p95 延迟突然升高怎么查？按 API、DB、Redis、模型、工具分段 trace，对比错误率、连接池、慢查询和队列深度。

## 6. 面试演示顺序

控制在 8 分钟：先用 30 秒讲业务问题；1 分钟展示架构；2 分钟演示知识上传和带引用回答；1 分钟演示危险操作进入审批；1 分钟展示 trace 与评估；1 分钟讲 Docker/CI；最后用 90 秒主动讲一次故障、修复和仍存在的边界。
