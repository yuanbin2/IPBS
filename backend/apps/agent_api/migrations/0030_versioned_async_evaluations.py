import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


def populate_case_keys(apps, schema_editor):
    EvaluationCase = apps.get_model("agent_api", "EvaluationCase")
    database = schema_editor.connection.alias
    for case in EvaluationCase.objects.using(database).filter(case_key__isnull=True).iterator():
        EvaluationCase.objects.using(database).filter(pk=case.pk).update(case_key=uuid.uuid4())


class Migration(migrations.Migration):
    dependencies = [("agent_api", "0029_evaluation_human_annotation")]

    operations = [
        migrations.AddField(
            model_name="evaluationcase",
            name="case_key",
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(
            code=populate_case_keys,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="evaluationcase",
            name="case_key",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.CreateModel(
            name="EvaluationDataset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("workspace_key", models.CharField(db_index=True, default="default", max_length=80)),
                ("version", models.CharField(max_length=80)),
                (
                    "status",
                    models.CharField(
                        choices=[("draft", "Draft"), ("frozen", "Frozen")], default="draft", max_length=16
                    ),
                ),
                ("manifest_hash", models.CharField(max_length=64)),
                ("snapshot", models.JSONField(default=list)),
                ("created_by", models.CharField(blank=True, max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("frozen_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ["-created_at"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("workspace_key", "version"), name="uniq_eval_dataset_version_workspace"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="EvaluationBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("workspace_key", models.CharField(db_index=True, default="default", max_length=80)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("completed", "Completed"),
                            ("partial", "Partial"),
                            ("failed", "Failed"),
                        ],
                        default="queued",
                        max_length=16,
                    ),
                ),
                ("total_cases", models.PositiveSmallIntegerField(default=0)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("request_hash", models.CharField(max_length=64)),
                ("idempotency_key", models.CharField(max_length=120)),
                ("celery_task_id", models.CharField(blank=True, max_length=120)),
                ("created_by", models.CharField(blank=True, max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "dataset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="batches",
                        to="agent_api.evaluationdataset",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("workspace_key", "idempotency_key"), name="uniq_eval_batch_idempotency"
                    ),
                    models.UniqueConstraint(
                        condition=Q(status__in=("queued", "running")),
                        fields=("workspace_key",),
                        name="uniq_active_eval_batch_per_workspace",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="EvaluationCaseResult",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("case_key", models.UUIDField()),
                ("order", models.PositiveSmallIntegerField()),
                ("case_snapshot", models.JSONField(default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("completed", "Completed"),
                            ("needs_review", "Needs review"),
                            ("failed", "Failed"),
                            ("skipped", "Skipped"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("passed", models.BooleanField(default=False)),
                ("error", models.TextField(blank=True)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("claim_task_id", models.CharField(blank=True, max_length=120)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="case_results",
                        to="agent_api.evaluationbatch",
                    ),
                ),
                (
                    "evaluation_run",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="batch_results",
                        to="agent_api.evaluationrun",
                    ),
                ),
            ],
            options={
                "ordering": ["order", "id"],
                "constraints": [
                    models.UniqueConstraint(fields=("batch", "case_key"), name="uniq_eval_result_per_case_batch"),
                    models.UniqueConstraint(fields=("batch", "order"), name="uniq_eval_result_order_batch"),
                ],
            },
        ),
    ]
