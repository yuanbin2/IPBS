from django.db import models

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
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    expected_answer = models.TextField(blank=True)
    category = models.CharField(max_length=30, choices=Category.choices)
    expected_route = models.CharField(max_length=40, blank=True)
    expected_agent = models.CharField(max_length=40, blank=True)
    reference_keywords = models.JSONField(default=list, blank=True)
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
