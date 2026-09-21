from django.db import migrations


ARTICLE_SLUG = "system-technology-stack"
OLD_TEXT = "Redis 作为缓存及 Celery broker；异步任务使用 Celery Worker 和 Celery Beat。"
NEW_TEXT = (
    "Redis 作为缓存和任务结果后端，RabbitMQ 作为 Celery broker；"
    "异步任务使用 Celery Worker 和 Celery Beat。"
)


def correct_system_tech_stack(apps, schema_editor):
    BlogArticle = apps.get_model("agent_api", "BlogArticle")
    for article in BlogArticle.objects.filter(slug=ARTICLE_SLUG):
        if OLD_TEXT not in article.content:
            continue
        article.content = article.content.replace(OLD_TEXT, NEW_TEXT)
        article.save(update_fields=["content", "updated_at"])


def restore_system_tech_stack(apps, schema_editor):
    BlogArticle = apps.get_model("agent_api", "BlogArticle")
    for article in BlogArticle.objects.filter(slug=ARTICLE_SLUG):
        if NEW_TEXT not in article.content:
            continue
        article.content = article.content.replace(NEW_TEXT, OLD_TEXT)
        article.save(update_fields=["content", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("agent_api", "0017_conversation_owner")]
    operations = [migrations.RunPython(correct_system_tech_stack, restore_system_tech_stack)]
