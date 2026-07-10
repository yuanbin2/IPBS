from django.db import migrations, models


def seed_mcp_tools(apps, schema_editor):
    MCPTool = apps.get_model("agent_api", "MCPTool")
    tools = [
        {
            "name": "local_file_search",
            "display_name": "本地文件搜索",
            "description": "在 README、docs 和 agent 目录中搜索公开项目资料。",
            "category": "filesystem",
            "permission_scope": "read:project_public_files",
            "is_enabled": True,
        },
        {
            "name": "git_repo_info",
            "display_name": "Git 仓库信息",
            "description": "读取当前分支、最近提交和工作区状态。",
            "category": "git",
            "permission_scope": "read:git_metadata",
            "is_enabled": True,
        },
        {
            "name": "web_search",
            "display_name": "网页搜索",
            "description": "外部网页搜索工具占位，默认关闭，避免未授权联网。",
            "category": "web",
            "permission_scope": "network:web_search",
            "is_enabled": False,
        },
        {
            "name": "safe_database_stats",
            "display_name": "安全数据库统计",
            "description": "只返回业务聚合指标，不暴露表结构和敏感字段。",
            "category": "database",
            "permission_scope": "read:aggregate_stats",
            "is_enabled": True,
        },
    ]
    for tool in tools:
        MCPTool.objects.get_or_create(name=tool["name"], defaults=tool)


def unseed_mcp_tools(apps, schema_editor):
    MCPTool = apps.get_model("agent_api", "MCPTool")
    MCPTool.objects.filter(
        name__in=["local_file_search", "git_repo_info", "web_search", "safe_database_stats"]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("agent_api", "0008_approval_request"),
    ]

    operations = [
        migrations.CreateModel(
            name="MCPTool",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80, unique=True)),
                ("display_name", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True)),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("filesystem", "Filesystem"),
                            ("git", "Git"),
                            ("web", "Web"),
                            ("database", "Database"),
                        ],
                        max_length=30,
                    ),
                ),
                ("permission_scope", models.CharField(blank=True, max_length=160)),
                ("is_enabled", models.BooleanField(default=True)),
                ("requires_approval", models.BooleanField(default=False)),
                ("config", models.JSONField(blank=True, default=dict)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["category", "name"],
            },
        ),
        migrations.RunPython(seed_mcp_tools, unseed_mcp_tools),
    ]
