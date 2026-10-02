import uuid

from django.db import models
from django.db.models import Q

from .agent import AgentRun, Conversation
from .constants import DEFAULT_WORKSPACE_KEY


class AgentObservation(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    conversation = models.ForeignKey(
        Conversation,
        related_name="observations",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    agent_run = models.ForeignKey(
        AgentRun,
        related_name="observations",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    input_message = models.TextField()
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    answer = models.TextField(blank=True)
    route = models.CharField(max_length=40, blank=True)
    selected_agent = models.CharField(max_length=40, blank=True)
    trace = models.JSONField(default=list, blank=True)
    tool_calls = models.JSONField(default=list, blank=True)
    sources = models.JSONField(default=list, blank=True)
    token_usage = models.JSONField(default=dict, blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    tool_success_rate = models.FloatField(default=1.0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUCCESS)
    failure_reason = models.TextField(blank=True)
    langsmith_project = models.CharField(max_length=120, blank=True)
    langsmith_run_id = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class EvaluationCase(models.Model):
    class Category(models.TextChoices):
        BLOG = "blog", "Blog"
        KNOWLEDGE = "knowledge", "Knowledge"
        COMPLEX = "complex", "Complex"
        JAILBREAK = "jailbreak", "Jailbreak"

    question = models.TextField()
    case_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    expected_answer = models.TextField(blank=True)
    category = models.CharField(max_length=30, choices=Category.choices)
    expected_route = models.CharField(max_length=40, blank=True)
    expected_agent = models.CharField(max_length=40, blank=True)
    reference_keywords = models.JSONField(default=list, blank=True)
    # Human-reviewable ground truth. Empty/draft annotations are never scored as truth.
    annotation = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "id"]

    def __str__(self) -> str:
        return self.question[:80]


class EvaluationRun(models.Model):
    case = models.ForeignKey(EvaluationCase, related_name="runs", on_delete=models.CASCADE)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    observation = models.ForeignKey(
        AgentObservation,
        related_name="evaluation_runs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    answer = models.TextField(blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    passed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class EvaluationDataset(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        FROZEN = "frozen", "Frozen"

    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    version = models.CharField(max_length=80)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    manifest_hash = models.CharField(max_length=64)
    snapshot = models.JSONField(default=list)
    created_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    frozen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=("workspace_key", "version"), name="uniq_eval_dataset_version_workspace")
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.get(pk=self.pk)
            immutable = ("workspace_key", "version", "manifest_hash", "snapshot", "created_by")
            if any(getattr(original, field) != getattr(self, field) for field in immutable):
                raise ValueError("Evaluation dataset snapshots are immutable; create a new version.")
            if original.status == self.Status.FROZEN and self.status != self.Status.FROZEN:
                raise ValueError("A frozen evaluation dataset cannot be unfrozen.")
        super().save(*args, **kwargs)


class EvaluationBatch(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        PARTIAL = "partial", "Partial"
        FAILED = "failed", "Failed"

    dataset = models.ForeignKey(EvaluationDataset, related_name="batches", on_delete=models.PROTECT)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    total_cases = models.PositiveSmallIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    request_hash = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=120)
    celery_task_id = models.CharField(max_length=120, blank=True)
    created_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=("workspace_key", "idempotency_key"), name="uniq_eval_batch_idempotency"),
            models.UniqueConstraint(
                fields=("workspace_key",),
                condition=Q(status__in=("queued", "running")),
                name="uniq_active_eval_batch_per_workspace",
            ),
        ]


class EvaluationCaseResult(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        NEEDS_REVIEW = "needs_review", "Needs review"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    batch = models.ForeignKey(EvaluationBatch, related_name="case_results", on_delete=models.CASCADE)
    case_key = models.UUIDField()
    order = models.PositiveSmallIntegerField()
    case_snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    evaluation_run = models.ForeignKey(
        EvaluationRun, related_name="batch_results", on_delete=models.SET_NULL, null=True, blank=True
    )
    passed = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    claim_task_id = models.CharField(max_length=120, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=("batch", "case_key"), name="uniq_eval_result_per_case_batch"),
            models.UniqueConstraint(fields=("batch", "order"), name="uniq_eval_result_order_batch"),
        ]
