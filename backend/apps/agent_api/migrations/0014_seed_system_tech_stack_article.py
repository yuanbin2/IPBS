from django.db import migrations
from django.utils import timezone


ARTICLE_SLUG = "system-technology-stack"


def seed_system_tech_stack_article(apps, schema_editor):
    BlogArticle = apps.get_model("agent_api", "BlogArticle")
    BlogArticle.objects.update_or_create(
        slug=ARTICLE_SLUG,
        defaults={
            "title": "本博客系统完整技术栈与架构",
            "summary": "本系统实际使用的前端、后端、数据库、Agent 与部署技术清单。",
            "content": (
                "本博客系统采用模块化全栈架构。\n\n"
                "前端使用 Vue 3、TypeScript、Vite、Pinia、Vue Router、Element Plus 和 md-editor-v3。\n\n"
                "后端使用 Python、Django、Django REST Framework（DRF）与 ASGI，运行层支持 Uvicorn 和 Gunicorn。\n\n"
                "数据层使用 PostgreSQL 与 pgvector，Redis 作为缓存和任务结果后端，RabbitMQ 作为 Celery broker；"
                "异步任务使用 Celery Worker 和 Celery Beat。\n\n"
                "Agent 层使用 LangChain、LangGraph、Agentic RAG、MCP、Human-in-the-loop（HITL）和 LangSmith。\n\n"
                "部署与工程化使用 Docker、Docker Compose、Nginx 和 GitHub Actions。"
            ),
            "status": "published",
            "published_at": timezone.now(),
        },
    )


def remove_system_tech_stack_article(apps, schema_editor):
    BlogArticle = apps.get_model("agent_api", "BlogArticle")
    BlogArticle.objects.filter(slug=ARTICLE_SLUG).delete()


class Migration(migrations.Migration):
    dependencies = [("agent_api", "0013_add_mcp_approval_action")]
    operations = [migrations.RunPython(seed_system_tech_stack_article, remove_system_tech_stack_article)]
