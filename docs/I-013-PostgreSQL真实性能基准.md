# I-013 PostgreSQL/pgvector 检索基准

状态：**待真实 PostgreSQL 实测**。本报告冻结方案和目标，当前没有性能结果。2026-10-23 在本机检查：`psql`/`pg_isready` 不在 PATH，`127.0.0.1:5432/5433` 无服务，Docker CLI 存在但 Docker Engine 管道不存在；隔离连接串加 `connect_timeout=3` 运行基准入口，退出 `django.db.utils.OperationalError: connection timeout expired`。没有生成结果 JSON，也没有修改现有数据库。

## 路径与索引盘点

- PostgreSQL 自动选 `pgvector`；`RAG_VECTOR_BACKEND=pgvector` 在 SQLite 上会拒绝本地回退。`search_knowledge_base()` 先生成 embedding，再做一次不兼容向量 `COUNT(*)`，随后调用 `search_pgvector()`；后者用 `agent_api_vectorindex` 联接 `DocumentChunk`/`Document`，过滤文档 ready、入库代际、向量 ready、8 项 embedding 身份及知识库/workspace，按余弦距离排序，取 `max(limit × 8, 24)` 个候选，再在 Python 中做混合打分、规则重排和文档多样性。基准的 `retrieval` 阶段复用这条数据库加排序路径，使用预计算合成向量以排除模型与网络时间；`vector` 阶段单独测 `search_pgvector()`。
- SQLite 本地路径迭代 ORM `EmbeddingRecord` 的 JSON 向量，用 Python 计算余弦相似度；它没有 pgvector HNSW 检索，也没有相同的 SQL 排序/联接计划。SQLite 单测只能验证逻辑，不能成为 I-013 的性能数据。
- 迁移 `0020` 建 `workspace_key, knowledge_base_id` B-tree 及 384/1536 维表达式 HNSW；`0028` 建 3072 维 `halfvec` HNSW；`0031` 增加 ready 行的 `(workspace_key, knowledge_base_id, provider, model, vector_dimensions)` 部分 B-tree。8 项身份条件和 ready 文档/代际联接可能影响计划，**是否用到 HNSW、是否有额外排序或重复扫描必须看实测 EXPLAIN**。不能由索引存在推定查询已优化。
- 文档和切片由 Django ORM 保存；pgvector 查询与写入使用原生 SQL，兼容性计数也是独立 SQL。基准捕获一次完整 `retrieval` 的 SELECT 次数和类型，并对两条 SQL 执行 `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`，只输出计划节点、索引、时间和块计数，不输出参数、SQL 正文或文档内容。若兼容性计数在无不兼容行的情况下扫描全量向量，应先由计划与耗时确认瓶颈，再讨论优化。

## 测试条件与判定目标（实测前冻结）

| 项 | 固定值 / 口径 |
| --- | --- |
| 数据库 | 新建空库，名称以 `blog_i013_bench_` 开头；本机或 CI PostgreSQL + pgvector；先迁移，基准拒绝已有知识库/文档/切片/向量的库 |
| 数据 | `i013-synthetic-v1`，seed 13013，384 维归一化确定性向量，1 个文档对应 1 个切片；累计 1,000、10,000 条；三个位置的精确向量作为查询，合成文本含唯一 marker |
| 并发与样本 | 每规模并发 1、4、8；每阶段先 10 次预热，再 100 次测量；每个 worker 使用独立 Django 数据库连接；两阶段为 `vector` 和 `retrieval` |
| 延迟 | 单次操作从函数调用到结果返回的墙钟时间；只统计成功请求的 P50/P95，失败单列；另记场景总墙钟时间。连接池/系统缓存不清空，按规模和并发顺序运行并记录这一顺序 |
| 质量 | 已知目标切片在 top 5 的比例与 top 1 比例；这只验证合成数据上的检索一致性，不代表真实语义问答质量，真实样本仍见 I-001 |
| 数据库开销 | 读取 `pg_stat_database` 前后差值：commit/rollback、磁盘/缓存块、返回/抓取行、临时字节和库大小；另存两条 SQL 的 `EXPLAIN ANALYZE BUFFERS` 节点、索引及运行时间。统计视图可能延迟刷新，因此差值是观察值而非精确单请求资源计费 |
| 硬件/版本 | 脚本记录操作系统、CPU/逻辑核、物理内存、PostgreSQL 版本、pgvector 版本、shared_buffers、work_mem、max_connections 与现有向量索引 |

**预设诊断目标**：错误率 0；合成目标 Recall@5 ≥ 99%；完整 `retrieval` 的数据库 SELECT 数不超过 2（一次兼容性计数、一次向量检索）；10,000 条/并发 1 的 `retrieval` P95 ≤ 250 ms、并发 8 的 P95 ≤ 750 ms。目标是本机隔离测试的诊断线，不是线上 SLA。未达到时保留原始结果，先看查询计划、重复查询与数据库块开销；只对实测瓶颈改代码/索引，原条件复测并比较目标召回。当前没有实测，所以**没有优化或权重调整**。

## 在隔离库运行

在本机启动 Docker Engine 后，从仓库根目录 PowerShell 执行。下面容器名、数据库名和端口专用于本基准；不要指向已有业务库。密码仅供本机隔离容器使用，可替换。

```powershell
docker run --name blog-i013-bench-local -e POSTGRES_USER=bench -e POSTGRES_PASSWORD=bench-local-only -e POSTGRES_DB=blog_i013_bench_local -p 127.0.0.1:55433:5432 -d pgvector/pgvector:0.8.6-pg16
$env:I013_BENCH_DATABASE_URL = 'postgres://bench:bench-local-only@127.0.0.1:55433/blog_i013_bench_local?connect_timeout=5'
$env:DATABASE_URL = $env:I013_BENCH_DATABASE_URL
$env:BLOG_LOCAL_MODE = 'false'
$env:DJANGO_SECRET_KEY = 'isolated-i013-benchmark-key-0123456789-0123456789-0123456789'
$env:DJANGO_HTTPS_TERMINATED = 'true'
$env:DJANGO_SECURE_SSL_REDIRECT = 'true'
$env:AGENT_SECURITY_ENFORCED = 'true'
$env:BLOG_MEDIA_STORAGE = 'file'
.\.venv\Scripts\python.exe backend/manage.py migrate --noinput
.\.venv\Scripts\python.exe backend/scripts/benchmark_pgvector_i013.py --sizes 1000,10000 --concurrency 1,4,8 --samples 100 --warmup 10 --seed 13013 --dimensions 384 --output docs/evaluation/i013-postgres-local.json
```

`migrate` 只可在上述新建隔离库执行。脚本忽略普通 `DATABASE_URL` 作为基准目标，必须显式设置 `I013_BENCH_DATABASE_URL`；它校验本地地址、独立库名前缀、Django 实际数据库、迁移、空库和维度索引。数据留在隔离库供查询计划复核；重跑需使用**另一个新空库**，不要在原库混入下一次样本。生成的 JSON 保存逐场景数据、错误类别、目标命中率和脱敏计划。公开或上传报告前复核主机与数据库元数据。

若要测 1536/3072 维，使用新的隔离库和 `--dimensions` 参数，分别报告，不与 384 维混算。真实 embedding/完整问答延迟、远程模型成本以及线上负载不在本基准范围内。

## 本次执行与后续判断

| 检查 | 结果 |
| --- | --- |
| 脚本参数/隔离保护单测 | 在 `backend` 目录用根 `.venv` 执行 `python -m unittest scripts.test_benchmark_pgvector_i013 -v`：4/4 通过；这不是数据库性能测试。另以 SQLite 临时测试库运行 `apps.agent_api.tests.test_embedding_spaces`：6/6，通过逻辑回归但不算 PostgreSQL 性能 |
| 黑盒入口 | 未设 `I013_BENCH_DATABASE_URL` 时拒绝执行；指向本机专用库名和关闭端口、`connect_timeout=3` 时约 4.6 秒以连接超时退出；未生成 JSON |
| PostgreSQL/pgvector 真实测量 | **未执行**；无可用数据库服务；P50/P95、错误率、数据库开销、查询计划、重复查询观察值均待验证 |
| 同条件优化复测 | **未执行**；没有实测瓶颈依据，未改生产检索代码或新增缓存/索引 |

后续拿到 JSON 后，应先核对版本/硬件/实际行数，再列每个规模和并发的 P50/P95、错误率、目标命中率、块读取/命中、临时字节以及 `vector_search` 和 `compatibility_count` 计划。若复测，保持相同容器版本、硬件、种子、维度、规模、并发、预热和测量次数，同时记录唯一改变项。I-013 在真实数据库测量及必要复测完成前保持开放。
