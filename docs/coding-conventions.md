# 代码规范手册（Coding Conventions）

> 本文件是系统**代码习惯的单一事实源（SSOT）**。写给三波人看：未来的自己、未来的协作者、AI。
> 本文档不重复 `design-blueprint.md`（业务/数据/迭代纪律总纲）与 `database-schema-reference.md`（字段级 schema）的内容，只回答一个问题：**代码怎么写**。
> 三份文档的分工：蓝图定「做什么、数据在哪」，schema 定「字段长什么样」，本手册定「代码长什么样」。

---

## 0. 这份手册解决什么问题

系统代码主体已按领域分包（`models/` `serializers/` `views/` `services/` `api_urls/`），但存在四类习惯不一致：

1. **依赖方向混乱**：`views/common.py` 用 `from .common import *` 星号导入兜底，`serializers/__init__.py` 同样星号导出——改一个文件不知道会影响谁。
2. **薄厚不均**：部分 View 把查询过滤、权限判断、序列化全写在 HTTP 方法里（`views/blog.py` 的列表过滤约 40 行），部分又正确下沉到 `services/`。
3. **接口形态不统一**：有的接口返回裸数组，有的返回对象，错误一律 `{"detail": "..."}`，没有 `code`，前端无法程序化处理。
4. **死代码与活代码并存**：`views.py`（1737 行）、`models.py`（428 行）、根级 `blog.py`/`blog_agent.py`、根目录 `agent/` 包均无活跃引用，但仍在仓库里，新人无法判断哪份是真的。

本手册做四件事：**① 定依赖方向**（谁能 import 谁）；**② 定 View/Service 边界**（后端 API 尽可能简单）；**③ 定统一接口形态**（响应/错误/分页/状态码）；**④ 给迁移路线图**（现状 → 目标，与蓝图 T1–T9 对齐）。

---

## 1. 总则：五条核心习惯

| # | 习惯 | 来源 | 一句话说明 |
| --- | --- | --- | --- |
| 1 | **先文档后代码** | 蓝图 3.3 | 功能迭代先登记编号、写清数据设计，再动代码；改完同步文档 |
| 2 | **功能编号进代码** | 蓝图 3.1 | 每个 View 类 docstring 标注功能编号（如 `CAB`），与蓝图功能清单、commit message 三者一致 |
| 3 | **一个文件一个职责** | 本手册 §2 | 单文件 ≤ 300 行；超 500 行必须拆分，没有例外 |
| 4 | **View 只做四件事** | 本手册 §4 | 解析请求 → 鉴权 → 调 Service → 返回响应。业务逻辑一行都不留在 View |
| 5 | **改动必留痕** | 蓝图 4.2 | 字段变更同步 schema 附录 A，接口变更同步 `api.md`，架构变更同步蓝图更新日志 |

> 习惯 1、2、5 是蓝图的纪律在代码层的投影；习惯 3、4 是本手册新增的代码层纪律。

---

## 2. 目录与模块划分规范

### 2.1 目标结构（当前结构的清理版）

```
backend/
├── config/                     # Django 配置（settings/urls/celery），不含业务
├── apps/
│   ├── agent_api/              # 唯一业务 app
│   │   ├── models/             # 对象 1-6 数据定义（每领域一个文件）
│   │   ├── serializers/        # 入参校验 + 出参序列化（每领域一个文件）
│   │   ├── views/              # HTTP 薄层（每领域一个文件 + common 共享件）
│   │   ├── services/           # 业务逻辑（每领域一个文件，可依赖 models/agent）
│   │   ├── api_urls/           # 路由（每领域一个文件，只做 path → view 映射）
│   │   ├── migrations/         # Django 迁移
│   │   └── tasks.py            # Celery 异步任务（只传主键，不传模型）
│   ├── core/                   # 横切：健康检查等
│   └── users/                  # 占位（用户模型以 auth.User 为准）
├── agent/                      # Agent 编排（LangGraph），被 services 调用
│   ├── multi_agent.py          # Supervisor 路由 + 图执行
│   ├── simple_agent.py         # 单Agent 工具调用
│   ├── mcp_tools.py            # MCP 工具注册与执行
│   ├── security.py             # 安全上下文/敏感词/JWT（横切）
│   └── tools.py                # 内置工具定义
└── manage.py
```

### 2.2 目录职责边界（谁能放什么）

| 目录 | 只放 | 禁止放 | 典型文件行数 |
| --- | --- | --- | --- |
| `models/` | Model 类、`TextChoices` 枚举、`Meta`、模型方法（`__str__` 等） | 查询逻辑、HTTP、import service/agent | ≤ 150 |
| `serializers/` | 入参校验函数、出参序列化函数（`serialize_xxx`） | 数据库写入、业务规则 | ≤ 150 |
| `views/` | `APIView` 子类：解析 → 鉴权 → 调 service → `Response` | 查询过滤拼装、LLM 调用、文件解析 | ≤ 300 |
| `services/` | 业务逻辑：检索、摄入、Agent 调用、发布流程 | `request`/`Response` 对象、URL 反向解析 | ≤ 400 |
| `api_urls/` | `path()` 声明 | 任何逻辑 | ≤ 60 |
| `agent/` | LangGraph 图、节点、工具定义、路由策略 | Django ORM 直接写业务表（经 services 传入数据） | ≤ 400 |
| `tasks.py` | `@shared_task` 函数体：取主键 → 调 service | 请求解析、响应构造 | ≤ 200 |

### 2.3 依赖方向（单向，禁止反向）

```
api_urls  →  views  →  services  →  models
                │           │
                │           └──→  agent/（编排与工具）
                └──→ serializers/（出入参形态）
```

**硬规则：**

1. `models/` 是终点：不 import 任何上层目录（services/views/agent 都不行）。
2. `services/` 不 import `views/`、`api_urls/`；需要请求上下文时，由 View 把上下文（`workspace_key`、`actor`、`role`）作为**普通参数**传进来，禁止把 `request` 对象传进 service。
3. `views/` 之间通过 `views/common.py` 共享基件，但**禁止星号导入**（见 §3.1）；共享件只放：鉴权帮助函数、分页帮助函数、错误响应帮助函数。
4. `agent/` 被 `services/` 调用；`agent/` 内部不 import Django models（数据由 service 层准备好传入）。
5. `api_urls/` 只 import `views/`，不 import `services/`、`models/`。

### 2.4 命名规范

| 对象 | 规范 | 示例 |
| --- | --- | --- |
| 文件/目录 | snake_case，领域名与蓝图模块对齐 | `views/blog.py`、`services/rag.py` |
| Model 类 | PascalCase，领域前缀 | `BlogArticle`、`DocumentChunk`（遵循 schema reference §2.1） |
| View 类 | `<领域><动作>View`，动作用 List/Create/Detail/Update/Delete/Chat/Stream 等 | `BlogArticleListCreateView` |
| Service 函数 | 动词开头，返回领域对象或数据类 | `ingest_document()`、`search_knowledge_base()` |
| 序列化函数 | `serialize_xxx` / `parse_xxx` | `serialize_article()` |
| 常量 | UPPER_SNAKE，模块级 | `DEFAULT_WORKSPACE_KEY`、`INDEXED_DIMENSIONS` |
| 私有帮助函数 | `_` 前缀 | `_get_or_create_conversation()` |
| 功能编号 | View 类 docstring 首行 | `"""CAB 文档上传：…"""` |

---

## 3. Python 代码风格

### 3.1 Import 规范（当前最大整改项）

**规则：**

1. **禁止星号导入**（`from x import *`）。现状 `views/common.py`、`views/*.py` 的 `from .common import *`、`from ..serializers import *` 全部改为显式命名导入——这是「改一处不知道影响谁」的根源。
2. 分组顺序，组间空一行：标准库 → 第三方 → Django/DRF → 本项目（`from ..models import` / `from agent.xxx import`）。
3. 一组内按字母序；一行一个 import（长括号列表除外）。
4. `try/except ImportError` 降级导入只允许出现在 `views/common.py` 一处（agent 模块缺失时的部署降级），其他地方直接导入。

```python
# ✗ 现状（禁止）
from .common import *
from ..serializers import *

# ✓ 目标
import logging
from datetime import timedelta

from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import BlogArticle
from ..serializers import serialize_article
from ..services.blog import publish_article_to_knowledge_base
```

**顺带清理**：`views/common.py` 当前 import 区存在连续双空行（疑似自动拼接产物），统一为单空行分组。

### 3.2 类型注解与 docstring

1. 所有公开函数（service 函数、序列化函数、模型方法）必须带参数与返回值注解。
2. View 的 HTTP 方法（`get`/`post`）可省略 `request` 注解，但 URL 参数要注解（`def get(self, request, pk: int)`）。
3. 模块级 docstring 一句话说明职责；公开类/函数 docstring 一句话说明「做什么 + 关键约束」，不写实现过程。

```python
def search_knowledge_base(query: str, *, workspace_key: str, knowledge_base_id: int | None = None,
                          top_k: int = 5) -> list[KnowledgeMatch]:
    """混合检索：向量相似度 0.72 + 关键词 0.28，仅返回 status=ready 的文档切片。"""
```

### 3.3 注释

1. 注释解释**为什么**，不解释做什么；代码能看懂的绝不注释。
2. 约束性注释必须写（如「只传主键确保消息可序列化」「幂等 upsert」），这类信息代码本身表达不了。
3. 删除被注释掉的死代码——git 历史就是历史，仓库里不留 `# "基础参数": {...}` 这类长注释块（`models/blog.py` 现状有，清理时移除，以 schema reference 文档为准）。

### 3.4 Django/DRF 习惯

| 场景 | 规范 | 现状符合度 |
| --- | --- | --- |
| 固定状态 | `TextChoices` 枚举，字段 `choices=` | ✅ 已遵守 |
| 动态结构 | `JSONField`，默认值 `default=list` / `default=dict` | ✅ 已遵守 |
| 多租户 | 业务表必带 `workspace_key`（`db_index=True`） | ✅ 已遵守 |
| 时间戳 | `created_at`（auto_now_add）/ `updated_at`（auto_now） | ✅ 已遵守 |
| 查询 | `select_related`/`prefetch_related` 消灭 N+1；列表接口必须显式限流（`[:50]` 之类） | ⚠️ 部分接口有 |
| 写操作 | 多表写入用 `transaction.atomic()` | ⚠️ 检查覆盖 |
| 异常 | 禁止裸 `except:`；捕获具体异常并 `logger.exception(...)` | ⚠️ 检查覆盖 |
| 调试 | 禁止 `print`；用 `logging.getLogger(__name__)` | ⚠️ 检查覆盖 |

### 3.5 格式与工具链

1. 行宽 **120**（`black` + `ruff` 配置 `line-length = 120`）。
2. `ruff` 启用规则集：`E`（pycodestyle）、`F`（pyflakes，含未使用导入）、`I`（import 排序）、`B`（bugbear）、`UP`（pyupgrade）。
3. 仓库根放 `pyproject.toml` 统一 black/ruff 配置；CI 加 `ruff check .` 与 `black --check .` 两道门（蓝图 T6 的 CI 已就绪，接上即可）。
4. 字符串统一双引号；尾随逗号（多行调用/字面量）。

---

## 4. 后端 API 设计规范（目标：尽可能简单）

### 4.1 薄 View 模板（本手册核心）

每个 View 方法严格四步，**业务逻辑不允许出现在第 1、4 步**：

```python
class BlogArticlePublishView(APIView):
    """BAB 文章发布：提交后进入审批或直接发布。"""

    authentication_classes = []
    permission_classes = []

    def post(self, request, slug: str):
        # 1. 解析 + 鉴权（只取参数、判断身份，不做业务规则）
        context = context_from_request(request)
        denied = require_roles(request, [UserProfile.Role.OPERATOR, UserProfile.Role.ADMIN])
        if denied:
            return denied

        # 2. 转成 service 入参（普通参数，不传 request）
        payload = parse_publish_payload(request.data)

        # 3. 调 service（所有业务规则都在这里）
        result = publish_article(slug=slug, payload=payload, actor=context.actor,
                                 workspace_key=get_workspace_key(request))

        # 4. 统一响应
        if result.error:
            return error_response(result.error)          # §4.4 统一错误
        return Response(serialize_article(result.article), status=status.HTTP_200_OK)
```

**反例（现状需下沉的逻辑）**：`views/blog.py` `BlogArticleListCreateView.get` 中约 40 行的 status/author/category/tag/q 组合过滤与权限分支——应下沉为 `services/blog.py` 的 `list_articles(filters: ArticleFilters, context: AccessContext)`，View 只负责把 query_params 解析成 `ArticleFilters`。

### 4.2 URL 规范

1. 资源用名词复数，动作用子资源：`blog/articles/`、`blog/articles/<slug>/publish/`。现状已遵守。
2. 按域分文件（`api_urls/` 每域一个），`urls.py` 只 include。现状已遵守。
3. **新增 API 必须登记 `api.md`**（蓝图 4.2 同步约定），并在 View docstring 标注功能编号。
4. 版本前缀（`/api/v1/`）列为路线图项：现有前端直连这些路径，批量改造成本高，约定**新域名 API 从 v1 开始**，存量渐进迁移（见 §9）。

### 4.3 请求规范

| 项 | 规范 |
| --- | --- |
| 参数解析 | 集中在 View 第一步，解析结果立即转为 dataclass/普通参数进 service；service 签名里不出现 `request` |
| 必填校验 | 缺失即 `400` + `code=missing_field` + `detail` 指明字段名；校验函数放 `serializers/`（如 `parse_publish_payload`） |
| 分页 | 列表统一 `limit`（默认 20，最大 100）+ `before`/`after` 游标（会话消息已用此模式，推广到全部列表）；响应带 `has_more` |
| 过滤 | query 参数白名单制：未登记的参数直接忽略；组合过滤逻辑在 service，不在 View |
| 上传 | `MultiPartParser`；文件类型/大小校验在 service；上传后立即转存，不依赖 request.FILES 生命周期 |

### 4.4 响应与错误规范（当前最不统一的一项）

**成功响应**：新 API 统一 envelope，老 API 保持原样直到迁移（§9 登记清单）：

```json
// 新规范（对象型资源）
{"data": {...}, "meta": {"request_id": "..."}}
// 新规范（列表型资源）
{"data": [...], "meta": {"has_more": false, "next_cursor": null}}
```

**错误响应**：统一三字段，`code` 供前端程序化分支，`detail` 供人看：

```json
{"detail": "password must be at least 8 characters", "code": "password_too_short"}
```

| HTTP 状态 | 含义 | 对应 `code` 示例 |
| --- | --- | --- |
| 400 | 参数错误/校验失败 | `missing_field`、`password_too_short` |
| 401 | 未登录/token 失效 | `not_authenticated`、`invalid_credentials` |
| 403 | 已登录但角色/workspace 不符 | `forbidden`、`insufficient_role` |
| 404 | 资源不存在（或不属于当前 workspace） | `not_found` |
| 409 | 状态冲突（如审批已处理完再审批） | `conflict` |
| 422 | 语义正确但无法执行（如 LLM 降级全失败） | `upstream_unavailable` |
| 500 | 未预期异常 | `internal_error`（日志必须带 trace） |

**落地方式**：`views/common.py` 增加 `error_response(detail, code, http_status)` 帮助函数 + DRF 自定义 `exception_handler`（把 `ValidationError`/`PermissionDenied`/`NotFound` 统一成上述三字段格式）。所有新代码禁止手写裸 `Response({"detail": ...})`。

### 4.5 鉴权规范

1. 每个 View **显式声明** `authentication_classes` / `permission_classes`，禁止依赖全局默认——现在全为空数组是显式声明，保持并写清原因（公开端点）。
2. 业务端点鉴权走 `views/common.py` 的两个现有帮助函数，不在 View 里手写角色判断：
   - `require_roles(request, [Role.ADMIN])` → 不满足返回 403 Response（现返回即 `denied`，直接 `return denied`）；
   - `context_from_request(request)` → 取 `actor/role/workspace_key/authenticated`。
3. 所有查询必须带 `workspace_key` 过滤（多租户隔离是硬约束，对应蓝图 AAG）；带 `owner_username` 的私有数据（会话）必须同时过滤两者。
4. 高危动作（删除/发布/执行 SQL/调用外部工具）必须走 `ApprovalRequest` 审批流（E 模块），禁止在 View 里直接执行。

### 4.6 流式与异步

1. SSE（`AgentChatStreamView`）用 `StreamingHttpResponse` + `content_type="text/event-stream"`；心跳与结束帧格式统一 `data: {...}\n\n`，错误也以 SSE 帧返回而非断连。
2. 耗时操作（文档解析/向量化）一律 Celery 异步，`tasks.py` 只传主键（现有纪律，保持）；HTTP 侧只负责入队与返回任务状态查询端点。
3. Nginx `proxy_buffering off`（蓝图 T3）是 SSE 可用的部署前提，改部署时必须一起验证。

### 4.7 一个接口的完成定义（DoD）

新 API 合并前逐项确认：

- [ ] View ≤ 30 行有效逻辑，业务在 service
- [ ] docstring 有功能编号，`api.md` 已登记
- [ ] 错误走统一格式，有 `code`
- [ ] 列表有 limit 上限；查询带 workspace 过滤
- [ ] 有测试：happy path + 鉴权失败 + 参数缺失
- [ ] 前端 `src/api/` 有对应 typed client 方法

---

## 5. 数据层规范（摘要，细则以 schema reference 为准）

1. 字段命名/类型/索引/删除策略全部遵循 `database-schema-reference.md`，本手册不重复；**唯一新增**：
2. `makemigrations` 之后必须做三件事：检查迁移文件可逆性 → 登记 schema reference 附录 A → 涉及接口的同步 `api.md`。
3. **禁止手改已应用的 migration**；发现错了就新建一个迁移修正。
4. `agent_api_vectorindex`（pgvector）不走 ORM：改 `services/vector_store.py` 的建表 SQL 时，同样登记附录 A（schema reference §3.5 已声明）。
5. 查询优化路径：先 `select_related`/`prefetch_related`，再考虑索引；新索引先登记 schema reference §5 待补清单再实施。

---

## 6. 前端规范（Vue 3 + TS，简要）

1. 目录按 feature 组织（现状已符合）：`features/<域>/{components,stores,composables,themes,utils}`；跨域共享才进 `components/`、`stores/`、`api/`。
2. 组件文件 ≤ 300 行；超了拆子组件或把逻辑抽 `composables/`。
3. API 调用只能经过 `src/api/` 的 typed client，禁止组件内直接 `fetch`/`axios`；client 方法与本手册 §4.4 的错误 envelope 对齐（`code` 做分支）。
4. TypeScript 严格模式，禁止 `any`（确有动态结构用 `unknown` + 收窄）。
5. 状态分层：服务端状态进 Pinia store，组件本地状态用 `ref`；store 内不出现组件逻辑。

---

## 7. 测试规范

1. **拆分**：`tests.py`（1882 行）按域拆成 `tests/` 包：`test_auth.py`、`test_blog.py`、`test_knowledge_rag.py`、`test_agent.py`、`test_governance.py`、`test_evaluation.py`、`test_security.py`（路线图 T6 一部分）。
2. 命名：`test_<行为>_<场景>_<期望>`，如 `test_publish_article_without_role_returns_403`。
3. 覆盖底线：每个 service 公开函数 ≥ 1 用例；每个新 API ≥ 3 用例（happy path / 鉴权失败 / 参数缺失）。
4. LLM/向量/外部 HTTP 一律 mock（现状用 `patch` + `RunnableLambda` 的模式保持）；测试不碰真实 API key。
5. Supervisor 路由单测（蓝图 DAG/T5）优先补——路由是纯函数，性价比最高。

---

## 8. 代码审查清单（Review Checklist）

每次提 PR/合并前过一遍：

- [ ] 符合 §2.3 依赖方向，无反向 import，无星号导入
- [ ] View 四步模板，无内联业务逻辑；文件行数达标
- [ ] 新 API：编号 docstring + `api.md` + 统一错误 envelope + 测试三件套
- [ ] 数据变更：migration + schema 附录 A + 蓝图日志三同步
- [ ] 查询带 `workspace_key`；列表有 limit；无 N+1
- [ ] 无 `print`、无裸 `except`、无注释掉的死代码
- [ ] 高危动作走审批流；敏感词/脱敏横切未被绕过

---

## 9. 迁移路线图（现状 → 目标）

> 与 `design-blueprint.md` 4.3 的 T1–T9 对齐；本表是**代码层**的执行口径。按优先级排序，每项独立可合并。
> **2026-09-23 已完成 C1–C8**（分支 `refactor/code-conventions-migration`，每项一个 commit，测试基线：92 个测试、5 个环境依赖的既有失败全程无新增）。

| 优先级 | 编号 | 动作 | 状态 |
| --- | --- | --- | --- |
| 高 | C1 | 删除死代码：`views.py`、`models.py`、根级 `blog.py`/`blog_agent.py` | ✅ 已完成 |
| 高 | C2 | 删除根目录 `agent/` 重复包；合并其更丰富的搜索触发词进 `backend/agent/multi_agent.py`；根 Dockerfile 去掉 `COPY agent` | ✅ 已完成 |
| 高 | C3 | `views/common.py` 与各 view 的星号导入改显式命名导入 | ✅ 已完成（顺带修复 `views/knowledge.py` 潜伏的 `models.Q` NameError） |
| 中 | C4 | `serializers/__init__.py` 星号导出改显式；三个重导出包加 `__all__` | ✅ 已完成 |
| 中 | C5 | View 内联查询逻辑下沉 service（`views/blog.py` 列表过滤） | ✅ 已完成（`ArticleListFilters` + `list_articles()`，附 6 个服务级测试） |
| 中 | C6 | 统一错误格式：`error_response()` + DRF `exception_handler` | ✅ 已完成（35 处手写错误响应全量转换，`code` 字段向后兼容） |
| 中 | C7 | 接工具链：根 `pyproject.toml`（black/ruff，行宽 120）+ CI 两道检查 + pre-commit | ✅ 已完成（含存量 lint 修复与 black 全量格式化） |
| 低 | C8 | `tests.py` 按域拆 `tests/` 包；补 Supervisor 路由单测 | ✅ 已完成（10 个域模块 + 6 个路由单测） |
| 低 | C9 | 新 API 启用响应 envelope；存量接口列迁移清单逐个切换 | 📋 已决策，见下方「C9 决策」 |
| 低 | C10 | `models/blog.py` 清理大段注释掉的示例参数 | ✅ 核实无需处理（注释块在已删除的死代码 `views.py` 里） |
| 低 | C11 | API 版本前缀决策 | 📋 已决策，见下方「C11 决策」 |

**执行纪律**：每项单独一个 commit，message 带编号（如 `refactor: C3 replace star imports in views with explicit imports`），完成后在蓝图更新日志登记一行。

### C9 决策：响应 envelope（2026-09-23）

- **新 API**：对象型用 `{"data": ..., "meta": {...}}`，列表型用 `{"data": [...], "meta": {"has_more", "next_cursor"}}`。
- **存量接口**：不做批量切换。前端 `src/api/` 与现有返回形态（裸数组/裸对象）深度耦合，一次性切换成本高、回归面大；按域逐个迁移，每域一个 commit 并同步前端。
- **迁移顺序建议**（按前端改动量从低到高）：`knowledge-bases`（已是对象数组）→ `documents` → `conversations` → `blog/*` → `agent/*`。
- 切换某个域前必须先补该域的接口测试（happy path + 错误路径），再改响应形态。

### C11 决策：API 版本前缀（2026-09-23）

- **不加 `/api/v1/` 前缀**。当前全部接口挂在 `/api/agent/` 与 `/api/` 下，前端、部署配置（Nginx/Railway/Cloudflare）均按此约定；加前缀需要三处同步改动而收益仅为理论上的版本管理。
- 约定改为：**未来若需版本化，以新路径段落地**（如 `/api/v2/agent/`），旧版并行维护一个迭代周期后下线；不在现有路径上追加版本号。

---

## 10. 与两份 SSOT 的关系

| 问题 | 查哪份文档 |
| --- | --- |
| 这个功能编什么号、归哪个对象空间、迭代流程 | `design-blueprint.md` |
| 这张表有哪些字段、什么索引、删除策略 | `database-schema-reference.md` |
| 这个文件该放哪、View 能写几行、错误怎么返回 | **本手册** |
| 三者冲突时 | 字段以代码为准并立即同步 schema；结构以蓝图为准；代码习惯以本手册为准 |

---

*本手册随代码演进持续更新。初始化于 2026-09-23。*
