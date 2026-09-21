from django.db import migrations, models


def add_current_time_tool(apps, schema_editor):
    MCPTool = apps.get_model("agent_api", "MCPTool")
    MCPTool.objects.update_or_create(
        name="current_time",
        defaults={
            "display_name": "当前时间",
            "description": "按 APP_TIMEZONE 配置直接返回服务器当前日期、时间和时区。",
            "category": "system",
            "permission_scope": "read:system_time",
            "is_enabled": True,
            "requires_approval": False,
            "config": {"timezone_env": "APP_TIMEZONE"},
        },
    )


def remove_current_time_tool(apps, schema_editor):
    MCPTool = apps.get_model("agent_api", "MCPTool")
    MCPTool.objects.filter(name="current_time").delete()


class Migration(migrations.Migration):
    dependencies = [("agent_api", "0015_upgrade_web_search_config")]
    operations = [
        migrations.AlterField(
            model_name="mcptool",
            name="category",
            field=models.CharField(
                choices=[
                    ("system", "System"),
                    ("filesystem", "Filesystem"),
                    ("git", "Git"),
                    ("web", "Web"),
                    ("database", "Database"),
                ],
                max_length=30,
            ),
        ),
        migrations.RunPython(add_current_time_tool, remove_current_time_tool),
    ]
