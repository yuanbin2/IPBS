from django.db import migrations


def upgrade_web_search(apps, schema_editor):
    MCPTool = apps.get_model("agent_api", "MCPTool")
    MCPTool.objects.filter(name="web_search").update(
        config={"provider": "duckduckgo", "max_results": 8, "strategy": "multi_query_rerank"}
    )


def downgrade_web_search(apps, schema_editor):
    MCPTool = apps.get_model("agent_api", "MCPTool")
    MCPTool.objects.filter(name="web_search").update(
        config={"provider": "duckduckgo", "max_results": 5}
    )


class Migration(migrations.Migration):
    dependencies = [("agent_api", "0014_seed_system_tech_stack_article")]
    operations = [migrations.RunPython(upgrade_web_search, downgrade_web_search)]
