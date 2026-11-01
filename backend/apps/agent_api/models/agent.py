import uuid

from django.db import models
from django.utils import timezone

from .constants import DEFAULT_WORKSPACE_KEY


class ConversationProject(models.Model):
    """对话项目：把会话按主题分组，替代一长条平铺的会话列表。"""

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=20, default="teal")
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    owner_username = models.CharField(max_length=150, default="anonymous", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_key", "owner_username", "name"], name="uniq_project_name_per_owner"
            )
        ]

    def __str__(self) -> str:
        return self.name


class Conversation(models.Model):
    title = models.CharField(max_length=160, blank=True)
    project = models.ForeignKey(
        ConversationProject,
        related_name="conversations",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    owner_username = models.CharField(max_length=150, default="anonymous", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.title or f"Conversation {self.pk}"


class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        AGENT = "agent", "Agent"

    conversation = models.ForeignKey(Conversation, related_name="messages", on_delete=models.CASCADE)
    agent_run = models.ForeignKey("AgentRun", related_name="messages", on_delete=models.SET_NULL, null=True, blank=True)
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField()
    tool_calls = models.JSONField(default=list, blank=True)
    sources = models.JSONField(default=list, blank=True)
    trace = models.JSONField(default=list, blank=True)
    token_usage = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class AgentRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    conversation = models.ForeignKey(Conversation, related_name="agent_runs", on_delete=models.CASCADE)
    run_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    request_id = models.CharField(max_length=36, blank=True, default="", db_index=True)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    input_message = models.TextField()
    request_fingerprint = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SUCCEEDED, db_index=True)
    cancel_requested = models.BooleanField(default=False)
    result = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    route = models.CharField(max_length=32, blank=True)
    tool_calls = models.JSONField(default=list, blank=True)
    sources = models.JSONField(default=list, blank=True)
    trace = models.JSONField(default=list, blank=True)
    token_usage = models.JSONField(default=dict, blank=True)
    model_calls = models.JSONField(default=list, blank=True)
    model_accounting = models.JSONField(default=dict, blank=True)
    stage_timings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
