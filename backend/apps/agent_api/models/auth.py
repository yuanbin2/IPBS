from django.conf import settings
from django.db import models

from .constants import DEFAULT_WORKSPACE_KEY


class UserProfile(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        OPERATOR = "operator", "Operator"
        VISITOR = "visitor", "Visitor"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name="agent_profile", on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VISITOR)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user_id"]


class SecurityAuditEvent(models.Model):
    class EventType(models.TextChoices):
        LOGIN = "login", "Login"
        ACCESS_DENIED = "access_denied", "Access denied"
        SENSITIVE_INPUT = "sensitive_input", "Sensitive input"
        OUTPUT_REDACTED = "output_redacted", "Output redacted"
        TOOL_BLOCKED = "tool_blocked", "Tool blocked"

    event_type = models.CharField(max_length=40, choices=EventType.choices)
    actor = models.CharField(max_length=120, blank=True)
    role = models.CharField(max_length=20, blank=True)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    path = models.CharField(max_length=240, blank=True)
    detail = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
