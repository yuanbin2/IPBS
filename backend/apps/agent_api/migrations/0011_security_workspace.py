from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_profiles_for_existing_users(apps, schema_editor):
    User = apps.get_model("auth", "User")
    UserProfile = apps.get_model("agent_api", "UserProfile")
    for user in User.objects.all():
        role = "admin" if user.is_superuser else "visitor"
        UserProfile.objects.get_or_create(user_id=user.id, defaults={"role": role, "workspace_key": "default"})


class Migration(migrations.Migration):
    dependencies = [
        ("agent_api", "0010_observability_evaluation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="workspace_key",
            field=models.CharField(db_index=True, default="default", max_length=80),
        ),
        migrations.AddField(
            model_name="agentobservation",
            name="workspace_key",
            field=models.CharField(db_index=True, default="default", max_length=80),
        ),
        migrations.AddField(
            model_name="approvalrequest",
            name="workspace_key",
            field=models.CharField(db_index=True, default="default", max_length=80),
        ),
        migrations.AddField(
            model_name="blogarticle",
            name="workspace_key",
            field=models.CharField(db_index=True, default="default", max_length=80),
        ),
        migrations.AddField(
            model_name="conversation",
            name="workspace_key",
            field=models.CharField(db_index=True, default="default", max_length=80),
        ),
        migrations.AddField(
            model_name="document",
            name="workspace_key",
            field=models.CharField(db_index=True, default="default", max_length=80),
        ),
        migrations.AddField(
            model_name="evaluationcase",
            name="workspace_key",
            field=models.CharField(db_index=True, default="default", max_length=80),
        ),
        migrations.AddField(
            model_name="evaluationrun",
            name="workspace_key",
            field=models.CharField(db_index=True, default="default", max_length=80),
        ),
        migrations.AddField(
            model_name="knowledgebase",
            name="workspace_key",
            field=models.CharField(db_index=True, default="default", max_length=80),
        ),
        migrations.AddField(
            model_name="mcptool",
            name="workspace_key",
            field=models.CharField(db_index=True, default="default", max_length=80),
        ),
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("admin", "Admin"), ("operator", "Operator"), ("visitor", "Visitor")], default="visitor", max_length=20)),
                ("workspace_key", models.CharField(db_index=True, default="default", max_length=80)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="agent_profile", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["user_id"]},
        ),
        migrations.CreateModel(
            name="SecurityAuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("login", "Login"), ("access_denied", "Access denied"), ("sensitive_input", "Sensitive input"), ("output_redacted", "Output redacted"), ("tool_blocked", "Tool blocked")], max_length=40)),
                ("actor", models.CharField(blank=True, max_length=120)),
                ("role", models.CharField(blank=True, max_length=20)),
                ("workspace_key", models.CharField(db_index=True, default="default", max_length=80)),
                ("path", models.CharField(blank=True, max_length=240)),
                ("detail", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.RunPython(seed_profiles_for_existing_users, migrations.RunPython.noop),
    ]
