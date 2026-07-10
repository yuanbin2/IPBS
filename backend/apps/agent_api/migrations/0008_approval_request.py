from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agent_api", "0007_blog_agent_models"),
    ]

    operations = [
        migrations.CreateModel(
            name="ApprovalRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("delete_document", "Delete document"),
                            ("delete_knowledge_base", "Delete knowledge base"),
                            ("delete_blog_article", "Delete blog article"),
                            ("publish_blog_article", "Publish blog article"),
                            ("execute_sql", "Execute SQL"),
                            ("external_deploy", "External deploy"),
                            ("send_email", "Send email"),
                        ],
                        max_length=40,
                    ),
                ),
                ("title", models.CharField(max_length=180)),
                ("description", models.TextField(blank=True)),
                ("payload", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("executed", "Executed"),
                            ("rejected", "Rejected"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("requester", models.CharField(blank=True, max_length=80)),
                ("reviewer", models.CharField(blank=True, max_length=80)),
                ("review_note", models.TextField(blank=True)),
                ("result", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("executed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
