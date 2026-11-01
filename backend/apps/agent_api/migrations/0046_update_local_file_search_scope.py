"""同步「本地文件搜索」工具描述到扩展后的实现。

背景：``local_file_search`` 原先硬编码 5 个源文件，其中 ``docs/day-01-blog.md``、
``day-02-notes.md``、``day-03-notes.md`` 早已不存在，实际只能搜到 README 一篇，
docs 下的设计/API/缺陷跟踪文档全部搜不到。实现已改为扫描根 README + docs/ 下
全部 Markdown（``agent/tools.py::search_project_files``），这里同步对外描述。

``ensure_default_mcp_tools()`` 用 ``get_or_create(defaults=...)``，只在首次创建行时
写入 defaults，无法修正既有行，因此补一个数据迁移（同 ``0044`` 的做法）。
"""

from django.db import migrations

NEW_DESCRIPTION = (
    "在根目录 README 与 docs/ 下全部 Markdown 说明文档中按关键词检索"
    "（含设计、API、数据库与缺陷跟踪文档），返回「文件:行号」便于定位；不含源码与知识库。"
)
OLD_DESCRIPTION = "在项目 README 与 docs 下的公开说明文档中按关键词检索；仅覆盖少量静态文档，不含知识库与源码。"


def update_description(apps, schema_editor):
    MCPTool = apps.get_model("agent_api", "MCPTool")
    MCPTool.objects.filter(name="local_file_search").update(description=NEW_DESCRIPTION)


def restore_description(apps, schema_editor):
    MCPTool = apps.get_model("agent_api", "MCPTool")
    MCPTool.objects.filter(name="local_file_search").update(description=OLD_DESCRIPTION)


class Migration(migrations.Migration):

    dependencies = [
        ("agent_api", "0045_blog_collection_auto_rule"),
    ]

    operations = [
        migrations.RunPython(update_description, restore_description),
    ]
