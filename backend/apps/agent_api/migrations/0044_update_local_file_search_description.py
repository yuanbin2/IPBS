"""修正「本地文件搜索」工具的对外描述，使其与实现保持一致。

背景：``local_file_search`` 的实现（``agent/tools.py::search_project_files``）只读取
README 与 docs 下的少量静态说明文档，并不扫描 ``agent`` 目录、源码或知识库。
原描述「在 README、docs 和 agent 目录中搜索公开项目资料。」与实现不符。

``ensure_default_mcp_tools()`` 使用 ``get_or_create(defaults=...)``，只在首次创建行时
写入 defaults，无法修正既有行，因此这里补一个数据迁移（同 ``0012_enable_web_search`` 的做法）。
"""

from django.db import migrations

NEW_DESCRIPTION = "在项目 README 与 docs 下的公开说明文档中按关键词检索；仅覆盖少量静态文档，不含知识库与源码。"
OLD_DESCRIPTION = "在 README、docs 和 agent 目录中搜索公开项目资料。"


def update_description(apps, schema_editor):
    MCPTool = apps.get_model("agent_api", "MCPTool")
    MCPTool.objects.filter(name="local_file_search").update(description=NEW_DESCRIPTION)


def restore_description(apps, schema_editor):
    MCPTool = apps.get_model("agent_api", "MCPTool")
    MCPTool.objects.filter(name="local_file_search").update(description=OLD_DESCRIPTION)


class Migration(migrations.Migration):

    dependencies = [
        ("agent_api", "0043_blogsetting"),
    ]

    operations = [
        migrations.RunPython(update_description, restore_description),
    ]
