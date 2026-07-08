from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("agent_api", "0006_seed_blog_articles"),
    ]

    operations = [
        migrations.CreateModel(
            name="BlogAgentSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("session_key", models.CharField(max_length=64, unique=True)),
                ("visitor_label", models.CharField(blank=True, max_length=80)),
                ("ip_hash", models.CharField(blank=True, max_length=64)),
                ("user_agent", models.TextField(blank=True)),
                ("is_blocked", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="BlogAgentSecurityEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("question", models.TextField()),
                ("reason", models.CharField(max_length=160)),
                ("ip_hash", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "session",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="security_events",
                        to="agent_api.blogagentsession",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="BlogAgentMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "role",
                    models.CharField(choices=[("user", "User"), ("agent", "Agent")], max_length=16),
                ),
                ("content", models.TextField()),
                ("sources", models.JSONField(blank=True, default=list)),
                ("trace", models.JSONField(blank=True, default=list)),
                ("token_usage", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="messages",
                        to="agent_api.blogagentsession",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
            },
        ),
    ]
