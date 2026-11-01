# 文档逐文件清单

> 审计起点：2026-10-05 本轮整理前，用仓库文件枚举发现 61 份 Markdown。每行记录用途/当前或历史状态、可验证实现来源、处理动作及理由；文档正文不作为实现现状的证据。未读取或复制 `.env`、浏览器 profile 或其他未提交源代码。根目录 Lark 导出和 `IPBS/欢迎.md` 仅按路径/标题识别为外部资料，未检查正文。

| 整理前路径 | 用途与状态 | 对应源码/配置/测试 | 动作及理由 |
| --- | --- | --- | --- |
| `README.md` | 当前使用/开发入口，或当前功能规格。 标题：智能个人博客与知识 Agent。 | `start.bat/start.sh, scripts/restart-local.ps1, docker-compose.yml, frontend/package.json` | 更新：修正与脚本、端口、权限、功能状态或识别限制的漂移。 |
| `lark-doc-llm-roadmap.md` | 个人或外部资料；非项目运行文档。 标题：从这里开始：目标、路线与学习方法。 | `关联源码、配置或测试；状态由 docs/缺陷跟踪表V2.0.md 交叉核对` | 保留且排除：不读取正文、不改写、不删除。 |
| `lark-doc-db-design.md` | 个人或外部资料；非项目运行文档。 标题：智控系统V2.0 数据库设计文档。 | `关联源码、配置或测试；状态由 docs/缺陷跟踪表V2.0.md 交叉核对` | 保留且排除：不读取正文、不改写、不删除。 |
| `lark-doc-content.md` | 个人或外部资料；非项目运行文档。 标题：一、需求分析。 | `关联源码、配置或测试；状态由 docs/缺陷跟踪表V2.0.md 交叉核对` | 保留且排除：不读取正文、不改写、不删除。 |
| `IPBS/欢迎.md` | 个人或外部资料；非项目运行文档。 标题：欢迎.md。 | `关联源码、配置或测试；状态由 docs/缺陷跟踪表V2.0.md 交叉核对` | 保留且排除：不读取正文、不改写、不删除。 |
| `app-desktop/README.md` | 当前使用/开发入口，或当前功能规格。 标题：Windows Edge App 启动器。 | `app-desktop/launch.bat, start-desktop.bat, scripts/restart-local.ps1` | 更新：修正与脚本、端口、权限、功能状态或识别限制的漂移。 |
| `docs/领域知识目录与系列博客设计V2.6.md` | 功能设计、阶段计划或验收记录；不等同全部验收完成。 标题：领域知识目录与系列博客设计 V2.6。 | `models/blog.py, blog_collections service/view, migration 0040` | 保留：在文档索引标明阶段状态，实际完成度以缺陷表为准。 |
| `docs/领域目录网页迁移设计V2.8.md` | 功能设计、阶段计划或验收记录；不等同全部验收完成。 标题：领域目录网页迁移设计 V2.8。 | `BlogCollection API exists; no full-site directory migration service` | 保留：在文档索引标明阶段状态，实际完成度以缺陷表为准。 |
| `docs/长截图OCR转Markdown与私有笔记设计V3.0.md` | 当前使用/开发入口，或当前功能规格。 标题：长截图 OCR 转 Markdown 与私有笔记设计 V3.0。 | `ScreenshotOcrDialog.vue, ocrWorker.ts, screenshotHandoff.ts` | 更新：修正与脚本、端口、权限、功能状态或识别限制的漂移。 |
| `docs/评论侧栏扩展设计V2.2.md` | 功能设计、阶段计划或验收记录；不等同全部验收完成。 标题：Blog V2.2 评论侧栏扩展设计。 | `blog_public views, BlogComment models, ArticleDetail.vue` | 保留：在文档索引标明阶段状态，实际完成度以缺陷表为准。 |
| `docs/评测与测试升级方案V2.0.md` | 功能设计、阶段计划或验收记录；不等同全部验收完成。 标题：评测与测试升级方案 V2.0。 | `evaluation models/views/tests and CI workflow` | 保留：在文档索引标明阶段状态，实际完成度以缺陷表为准。 |
| `docs/网页剪藏到博客设计V2.9.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：网页剪藏到博客设计 V2.9。 | `browser-extension sources, webClipHandoff.ts, private note APIs` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/网页剪藏修复验收记录V2.9.2.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：通用网页剪藏定点修复与验收 V2.9.2。 | `extension shared modules, frontend webClipHandoff, E2E specs` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/缺陷跟踪表V2.0.md` | 功能设计、阶段计划或验收记录；不等同全部验收完成。 标题：Blog V2.0 缺陷跟踪表。 | `referenced source/tests plus dated local/CI evidence` | 保留：在文档索引标明阶段状态，实际完成度以缺陷表为准。 |
| `docs/浏览器扩展连接博客设计V2.7.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：浏览器扩展连接博客设计 V2.7。 | `older LeetCode extension design; current browser-extension implementation` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/智能体答案质量与人工复核计划V2.4.md` | 功能设计、阶段计划或验收记录；不等同全部验收完成。 标题：智能体答案质量与人工复核计划 V2.4。 | `evaluation.py, scorer/tests, B-008/B-009` | 保留：在文档索引标明阶段状态，实际完成度以缺陷表为准。 |
| `docs/数据库设计文档V2.0.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：数据库设计文档 V2.0。 | `models/, migrations/, vector_store.py; snapshot dated 2026-10-04` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/截图OCR跨屏图片识别设计V3.1.md` | 当前使用/开发入口，或当前功能规格。 标题：截图 OCR 跨屏图片识别与保留设计 V3.1。 | `pixelImageCandidates.ts, longScreenshot.ts, ScreenshotOcrDialog.vue, screenshot E2E` | 更新：修正与脚本、端口、权限、功能状态或识别限制的漂移。 |
| `docs/发布阻断审查V2.0.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：Blog V2 发布阻断审查。 | `CI workflow, security settings, defect tracker dated snapshot` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/博客图片清理说明V2.0.md` | 功能设计、阶段计划或验收记录；不等同全部验收完成。 标题：博客图片清理说明 V2.0。 | `blog_image_cleanup.py, prune_blog_media management command` | 保留：在文档索引标明阶段状态，实际完成度以缺陷表为准。 |
| `docs/力扣题目与题解导入设计V2.5.md` | **已取消设计（2026-10-07）**：功能被主动删除，代码已移除，本文仅作历史存档。 标题：力扣题目与题解导入设计 V2.5。 | 已删除：`leetcode_link_import.py`、`LeetcodeImportDialog.vue`、`/blog/imports/leetcode/link-preview/` 路由 | 保留（历史存档）：顶部已加取消横幅，缺陷表 B-041 标记为已取消。 |
| `docs/写作阅读与笔记体验升级计划V2.1.md` | 功能设计、阶段计划或验收记录；不等同全部验收完成。 标题：写作、阅读与笔记体验升级计划 V2.1。 | `PrivateNotesDrawer.vue, ArticleDetail.vue, BlogWriter.vue` | 保留：在文档索引标明阶段状态，实际完成度以缺陷表为准。 |
| `docs/SYSTEM_KNOWLEDGE_BASE.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：企业知识智能体平台 — 系统知识库。 | `compare old route/entity list with config/urls.py and api_urls/` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/resume.md` | 个人或外部资料；非项目运行文档。 标题：简历项目包装。 | `personal material; no source authority` | 保留且排除：不读取正文、不改写、不删除。 |
| `docs/restful-async-architecture.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：RESTful、异步任务与 JWT 架构说明。 | `agent_api/api_urls/auth.py and frontend API client; auth changed to cookies` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/repair-report.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：项目修复与验证报告。 | `historical Docker/Nginx repair; current config is source` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/python-fullstack-interview-guide.md` | 个人或外部资料；非项目运行文档。 标题：卫晓斌 Python 全栈开发面试作战手册。 | `personal interview material; project claims need source verification` | 保留且排除：不读取正文、不改写、不删除。 |
| `docs/project-structure.md` | 当前使用/开发入口，或当前功能规格。 标题：当前代码目录。 | `backend/, frontend/src/, browser-extension/, app-desktop/` | 更新：修正与脚本、端口、权限、功能状态或识别限制的漂移。 |
| `docs/models-design.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：数据模型独立分层与实例表。 | `agent_api/models/*.py; current model fields are authoritative` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/job-preparation-guide.md` | 个人或外部资料；非项目运行文档。 标题：全栈工程师岗位准备与项目学习指南。 | `personal learning material; project claims need source verification` | 保留且排除：不读取正文、不改写、不删除。 |
| `docs/HTML导入Markdown博客设计V2.4.md` | 功能设计、阶段计划或验收记录；不等同全部验收完成。 标题：HTML 导入 Markdown 博客设计 V2.4。 | `HtmlImportDialog.vue, views/blog_imports.py, services/html_import.py` | 保留：在文档索引标明阶段状态，实际完成度以缺陷表为准。 |
| `docs/final-blog-post.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：从 RAG Demo 到企业级 Agent 平台：14 天工程化实践复盘。 | `narrative; verify project claims against current source` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/evaluation-report.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：项目评估报告。 | `compare old test claims with current evaluation plan and CI` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/design-blueprint.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：Blog/Agent 系统设计蓝图与迭代手册。 | `compare old doc map with docs/README.md and tracker` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/deployment.md` | 当前使用/开发入口，或当前功能规格。 标题：本地运行与 Compose 部署。 | `root launch scripts, scripts/restart-local.ps1, docker-compose.yml, backend/config/settings.py` | 更新：修正与脚本、端口、权限、功能状态或识别限制的漂移。 |
| `docs/demo-script.md` | 当前使用/开发入口，或当前功能规格。 标题：演示视频脚本。 | `frontend router, BlogView.vue, security/approval views` | 更新：修正与脚本、端口、权限、功能状态或识别限制的漂移。 |
| `docs/database-schema-reference.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：数据库字段参考手册（Database Schema Reference）。 | `agent_api/models/*.py and migrations/` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/database-er-diagram.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：数据库结构图。 | `agent_api/models/*.py and migrations/` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/database-design.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：当前系统数据库设计说明。 | `models/, vector_store.py, migrations/ (old design conflicts with present vector code)` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/coding-conventions.md` | 通用规范建议，含 2026-09 日期化迁移快照；目录/现状表述需核验。 | `backend/apps/agent_api/views/, serializers/, services/, urls.py; pyproject.toml and CI` | 更新：保留风格建议，将目录和 API/DB 事实入口改指当前文档与源码。 |
| `docs/Blog设计文档V2.0.md` | 功能设计、阶段计划或验收记录；不等同全部验收完成。 标题：Blog 设计文档 V2.0。 | `关联源码、配置或测试；状态由 docs/缺陷跟踪表V2.0.md 交叉核对` | 保留：在文档索引标明阶段状态，实际完成度以缺陷表为准。 |
| `docs/backend-deployment-guide.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：Django 后端部署指南。 | `current Django settings and Compose contradict old platform steps` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/architecture.md` | 当前使用/开发入口，或当前功能规格。 标题：当前架构概览。 | `backend/config/urls.py, docker-compose.yml, backend/agent and services` | 更新：修正与脚本、端口、权限、功能状态或识别限制的漂移。 |
| `docs/architecture-analysis.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：全项目架构分析报告。 | `old snapshot compared with backend/ and current defect tracker` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `docs/api.md` | 当前使用/开发入口，或当前功能规格。 标题：当前 API 索引。 | `backend/config/urls.py, agent_api/api_urls/*, View permissions` | 更新：修正与脚本、端口、权限、功能状态或识别限制的漂移。 |
| `docs/Agent能力增强与验证记录V2.3.md` | 功能设计、阶段计划或验收记录；不等同全部验收完成。 标题：Agent 能力增强与验证记录 V2.3。 | `backend agent services/views/tests` | 保留：在文档索引标明阶段状态，实际完成度以缺陷表为准。 |
| `backend/agent/README.md` | 当前使用/开发入口，或当前功能规格。 标题：后端 Agent 运行时代码。 | `backend/agent/*.py, agent_api/views/chat.py, tasks.py` | 更新：修正与脚本、端口、权限、功能状态或识别限制的漂移。 |
| `browser-extension/README.md` | 当前使用/开发入口，或当前功能规格。 标题：通用网页剪藏扩展：把当前网页送进我的私有笔记（或博客草稿）。 | `browser-extension/manifest.json, shared/*, ScreenshotOcrDialog.vue, longScreenshot.ts, pixelImageCandidates.ts` | 更新：修正与脚本、端口、权限、功能状态或识别限制的漂移。 |
| `backend/apps/agent_api/models/README.md` | 当前使用/开发入口，或当前功能规格。 标题：Django 模型层。 | `backend/apps/agent_api/models/*.py, migrations/` | 更新：修正与脚本、端口、权限、功能状态或识别限制的漂移。 |
| `desktop/CHANGELOG.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：Changelog。 | `desktop/package.json; no current release workflow` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `desktop/IMPLEMENTATION_SUMMARY.md` | 历史设计、状态快照或决策/验收记录；可能与当前实现不一致。 标题：Knowledge Agent Desktop - Implementation Summary。 | `desktop/electron/, desktop/src/, package.json` | 保留并标为历史：保留技术决策与测试证据，索引不作为当前操作入口。 |
| `desktop/CONTRIBUTING.md` | 当前使用/开发入口，或当前功能规格。 标题：Contributing to Knowledge Agent Desktop。 | `desktop/package.json scripts` | 更新：修正与脚本、端口、权限、功能状态或识别限制的漂移。 |
| `desktop/README.md` | 当前使用/开发入口，或当前功能规格。 标题：实验性 Electron 桌面原型。 | `desktop/package.json, vite.config.js, electron.vite.config.ts` | 更新：修正与脚本、端口、权限、功能状态或识别限制的漂移。 |
| `desktop/QUICKSTART.md` | 当前使用/开发入口，或当前功能规格。 标题：桌面原型快速入口。 | `desktop/package.json, vite.config.js` | 更新：修正与脚本、端口、权限、功能状态或识别限制的漂移。 |
| `docs/GLM5.1实现浏览器扩展提示词V2.7.md` | 旧提示词或重复图示；只记录清理前用途。 标题：旧扩展实施提示词。 | `current extension and B-043/B-044 tracker entries` | 删除：已被当前实现、设计和缺陷验收证据替代；架构图已合并。 |
| `docs/GLM5.3实现长截图OCR导入提示词V3.0.md` | 旧提示词或重复图示；只记录清理前用途。 标题：长截图 OCR 实施提示词。 | `ScreenshotOcrDialog, ocrWorker, B-045 evidence` | 删除：已被当前实现、设计和缺陷验收证据替代；架构图已合并。 |
| `docs/GLM实现力扣导入功能提示词V2.5.md` | 旧提示词或重复图示；只记录清理前用途。 标题：力扣导入实施提示词。 | `LeetCode design, service, UI and B-041 evidence` | 删除：已被当前实现、设计和缺陷验收证据替代；架构图已合并。 |
| `docs/GLM实现领域目录功能提示词V2.6.md` | 旧提示词或重复图示；只记录清理前用途。 标题：领域目录实施提示词。 | `collection models/API/design and B-042 evidence` | 删除：已被当前实现、设计和缺陷验收证据替代；架构图已合并。 |
| `docs/网页剪藏到博客实现提示词V2.9.md` | 旧提示词或重复图示；只记录清理前用途。 标题：网页剪藏旧实施提示词。 | `superseded extension and private note flow` | 删除：已被当前实现、设计和缺陷验收证据替代；架构图已合并。 |
| `docs/通用网页剪藏替换力扣扩展并导入私有笔记提示词V2.9.1.md` | 旧提示词或重复图示；只记录清理前用途。 标题：通用剪藏实施提示词。 | `extension README and V2.9.2 implementation evidence` | 删除：已被当前实现、设计和缺陷验收证据替代；架构图已合并。 |
| `docs/system-architecture.md` | 旧提示词或重复图示；只记录清理前用途。 标题：早期系统架构图。 | `duplicate of current architecture.md and Compose topology` | 删除：已被当前实现、设计和缺陷验收证据替代；架构图已合并。 |

## 本轮新增文件（不计入整理前 61 份）

- `docs/README.md`：当前文档索引。
- `docs/database-current.md`：源码核对后的当前数据库与媒体边界摘要。
- 本清单自身。

工作区开始前已处于删除状态的 `docs/day-*.md` 不在这 61 份中，本次未恢复或清理；`backend/agent/tools.py` 与 `backend/apps/agent_api/services/blog_public_retrieval.py` 仍枚举其中部分旧路径。因本任务限定文档整理，未改动业务代码；这些路径若继续用于运行时检索，应由后续代码任务单独处理。
