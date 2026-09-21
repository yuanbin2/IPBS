from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agent_api", "0012_enable_web_search")]
    operations = [
        migrations.AlterField(
            model_name="approvalrequest",
            name="action",
            field=models.CharField(
                choices=[
                    ("delete_document", "Delete document"),
                    ("delete_knowledge_base", "Delete knowledge base"),
                    ("delete_blog_article", "Delete blog article"),
                    ("publish_blog_article", "Publish blog article"),
                    ("execute_sql", "Execute SQL"),
                    ("execute_mcp_tool", "Execute MCP tool"),
                    ("external_deploy", "External deploy"),
                    ("send_email", "Send email"),
                ],
                max_length=40,
            ),
        )
    ]
