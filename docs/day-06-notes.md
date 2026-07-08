# Day 6: 个人博客系统开发

第六天的目标是把个人博客和 Agent 结合起来，让博客不只是内容展示页，而是个人知识库的入口。

## 学习目标

- 理解博客系统和知识库系统的关系。
- 使用 Django 建模文章、分类、标签、评论、浏览量和发布状态。
- 使用 Vue 做首页、文章列表、文章详情、标签、归档和关于我页面。
- 让文章发布后自动进入知识库，成为 Agent 可以检索和引用的资料。

## 后端实现

新增博客模型：

- `ArticleCategory`：文章分类。
- `ArticleTag`：文章标签。
- `BlogArticle`：文章主体，包含草稿、发布、归档状态。
- `BlogComment`：文章评论。

新增文章 API：

- `GET /api/agent/blog/articles/`：文章列表，支持分类、标签和关键词筛选。
- `POST /api/agent/blog/articles/`：创建文章，可直接发布并写入知识库。
- `GET /api/agent/blog/articles/<slug>/`：文章详情，并记录浏览量。
- `PATCH /api/agent/blog/articles/<slug>/`：更新文章。
- `POST /api/agent/blog/articles/<slug>/publish/`：发布文章并同步到知识库。
- `GET /api/agent/blog/articles/<slug>/comments/`：文章评论列表。
- `POST /api/agent/blog/articles/<slug>/comments/`：创建文章评论。
- `POST /api/agent/blog/images/`：上传博客图片，返回图片 URL 和 Markdown 图片语法。
- `GET /api/agent/blog/categories/`：分类列表。
- `GET /api/agent/blog/tags/`：标签列表。
- `GET /api/agent/blog/archive/`：文章归档。
- `GET /api/agent/blog/about/`：关于我信息。

## 知识库联动

文章发布时会生成一份 `Document`：

```text
BlogArticle -> Document(content_text) -> chunk -> embedding -> Agentic RAG retrieval
```

这样用户不只可以阅读文章，还可以在聊天页问：

- “你做过哪些 LangGraph 项目？”
- “这个项目的架构是什么？”
- “你的 Agentic RAG 是怎么实现的？”
- “你最近的技术栈是什么？”

## 前端实现

新增 `/blog` 页面，包含：

- 文章列表。
- 文章详情。
- 标签筛选。
- 分类筛选。
- 归档展示。
- 关于我模块。
- 基于开源 `md-editor-v3` 的 Markdown 写作台，支持工具栏、实时预览、全屏、标题、加粗、代码块、引用、列表、链接、表格、图片上传等笔记/博客写作能力。
- 发布并加入知识库。
- 文章详情页一键让 Agent 总结文章。
- 评论列表和评论发布。

如果文章还没有进入知识库，详情页会展示“同步到知识库”按钮，用于补录旧文章。

## 内容任务

本次初始化了 3 篇技术文章：

- LangGraph 入门：从线性 Chain 到状态图工作流。
- Agentic RAG 实战：让智能体自己判断是否需要检索。
- 项目架构设计：Vue + Django + LangGraph 的全栈知识助手。

## 当前限制

- 初始化文章由迁移写入数据库，但不会在迁移阶段直接调用 embedding；需要通过文章发布接口或详情页同步按钮进入知识库。
- Markdown 编辑和渲染已接入 `md-editor-v3`；后续可以继续扩展目录、更多主题、Mermaid、公式和代码高亮配置。
- 评论当前为免登录发布，适合学习演示；生产环境需要增加审核、限流和反垃圾策略。
- 图片上传当前限制 5MB，支持 jpg、png、gif、webp 和 svg；生产环境建议接入对象存储、鉴权和内容安全检查。
- 博客内容进入知识库后仍依赖当前 RAG 检索质量，后续需要继续优化 chunk、rerank 和引用展示。

## 今日验证

- 后端测试：`.venv\Scripts\python.exe manage.py test apps.agent_api`
- 前端构建：`npm run build`
