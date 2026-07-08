from django.db import migrations
from django.utils import timezone


def seed_blog_articles(apps, schema_editor):
    ArticleCategory = apps.get_model("agent_api", "ArticleCategory")
    ArticleTag = apps.get_model("agent_api", "ArticleTag")
    BlogArticle = apps.get_model("agent_api", "BlogArticle")

    category, _ = ArticleCategory.objects.get_or_create(
        slug="agent-engineering",
        defaults={"name": "Agent 工程", "description": "LangGraph、RAG 与企业智能体工程实践。"},
    )

    tag_names = ["LangGraph", "Agentic RAG", "项目架构"]
    tags = []
    for name in tag_names:
        tag, _ = ArticleTag.objects.get_or_create(
            slug=name.lower().replace(" ", "-"),
            defaults={"name": name},
        )
        tags.append(tag)

    articles = [
        {
            "title": "LangGraph 入门：为什么 Agent 需要状态图",
            "slug": "langgraph-intro-stategraph",
            "summary": "从线性 chain 过渡到 StateGraph，理解节点、边和条件路由如何组织复杂 Agent。",
            "content": (
                "LangGraph 适合把 Agent 拆成明确的状态节点。相比单条 chain，状态图可以表达分类、"
                "工具调用、检索、重写问题、生成答案和保存历史等多个阶段。\n\n"
                "在本项目中，Day3 把简单 Agent 改造成 StateGraph，形成 query/classify、retrieve、"
                "generate、save 等节点，为后续 Agentic RAG 打下基础。"
            ),
        },
        {
            "title": "Agentic RAG 实践：让 Agent 判断是否需要检索",
            "slug": "agentic-rag-practice",
            "summary": "Agentic RAG 不只是检索后回答，而是让 Agent 决定是否检索、是否重写问题、如何引用来源。",
            "content": (
                "普通 RAG 往往是固定流水线：用户问题、检索、拼接 prompt、生成答案。Agentic RAG 则加入"
                "决策节点：query_analyzer 判断是否检索，grade_documents 判断结果是否相关，rewrite_query "
                "在结果不足时改写问题。\n\n"
                "本项目 Day5 已经把回答升级为带引用来源的 Agentic RAG，让每个知识库回答都能展示文档标题、"
                "chunk 和相似度。"
            ),
        },
        {
            "title": "项目架构设计：Vue + Django + LangGraph 的个人知识博客",
            "slug": "project-architecture-vue-django-langgraph",
            "summary": "博客内容本身就是 Agent 的知识来源，访客可以阅读文章，也可以向 Agent 询问项目经历。",
            "content": (
                "这个项目不是普通 CMS，而是个人博客和企业知识 Agent 的结合体。前端使用 Vue 3，后端使用"
                "Django REST Framework，Agent 部分使用 LangChain 和 LangGraph。\n\n"
                "文章发布后会自动进入知识库，经过切分和 embedding，成为 Agent 回答问题的上下文。"
                "因此博客既是内容展示系统，也是可交互的个人技术简历。"
            ),
        },
    ]

    for item in articles:
        article, created = BlogArticle.objects.get_or_create(
            slug=item["slug"],
            defaults={
                "title": item["title"],
                "summary": item["summary"],
                "content": item["content"],
                "category": category,
                "status": "published",
                "published_at": timezone.now(),
            },
        )
        if created:
            article.tags.set(tags)


def unseed_blog_articles(apps, schema_editor):
    BlogArticle = apps.get_model("agent_api", "BlogArticle")
    BlogArticle.objects.filter(
        slug__in=[
            "langgraph-intro-stategraph",
            "agentic-rag-practice",
            "project-architecture-vue-django-langgraph",
        ]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("agent_api", "0005_blog_models"),
    ]

    operations = [
        migrations.RunPython(seed_blog_articles, unseed_blog_articles),
    ]
