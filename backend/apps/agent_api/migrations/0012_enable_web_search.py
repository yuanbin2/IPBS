from django.db import migrations


def enable_web_search(apps, schema_editor):
    MCPTool = apps.get_model("agent_api", "MCPTool")
    MCPTool.objects.filter(name="web_search").update(
        display_name="网页搜索",
        description="通过 DuckDuckGo 公共 JSON API 搜索外部网页，无需 API Key。",
        permission_scope="network:web_search",
        is_enabled=True,
        config={"provider": "duckduckgo", "max_results": 5},
    )


def disable_web_search(apps, schema_editor):
    MCPTool = apps.get_model("agent_api", "MCPTool")
    MCPTool.objects.filter(name="web_search").update(
        description="外部网页搜索工具占位，默认关闭。",
        is_enabled=False,
        config={},
    )


class Migration(migrations.Migration):
    dependencies = [("agent_api", "0011_security_workspace")]
    operations = [migrations.RunPython(enable_web_search, disable_web_search)]
