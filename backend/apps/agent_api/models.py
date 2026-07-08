from django.db import models


class Conversation(models.Model):
    title = models.CharField(max_length=160, blank=True)
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
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField()
    tool_calls = models.JSONField(default=list, blank=True)
    trace = models.JSONField(default=list, blank=True)
    token_usage = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class AgentRun(models.Model):
    conversation = models.ForeignKey(Conversation, related_name="agent_runs", on_delete=models.CASCADE)
    input_message = models.TextField()
    route = models.CharField(max_length=32, blank=True)
    tool_calls = models.JSONField(default=list, blank=True)
    trace = models.JSONField(default=list, blank=True)
    token_usage = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
