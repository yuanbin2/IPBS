"""Durable chat run identity, state, and message association."""

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def assign_run_ids(apps, schema_editor):
    agent_run = apps.get_model("agent_api", "AgentRun")
    for pk in agent_run.objects.using(schema_editor.connection.alias).values_list("pk", flat=True).iterator():
        agent_run.objects.using(schema_editor.connection.alias).filter(pk=pk).update(run_id=uuid.uuid4())


class Migration(migrations.Migration):
    dependencies = [("agent_api", "0046_update_local_file_search_scope")]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="run_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(assign_run_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="agentrun",
            name="run_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="request_fingerprint",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("running", "Running"),
                    ("succeeded", "Succeeded"),
                    ("failed", "Failed"),
                    ("cancelled", "Cancelled"),
                ],
                db_index=True,
                default="succeeded",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="cancel_requested",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="result",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="error_code",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="updated_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="finished_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="message",
            name="agent_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="messages",
                to="agent_api.agentrun",
            ),
        ),
    ]
