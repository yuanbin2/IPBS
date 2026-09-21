from django.db import models

from .constants import DEFAULT_WORKSPACE_KEY


class ApprovalRequest(models.Model):
    class Action(models.TextChoices):
        DELETE_DOCUMENT = "delete_document", "Delete document"
        DELETE_KNOWLEDGE_BASE = "delete_knowledge_base", "Delete knowledge base"
        DELETE_BLOG_ARTICLE = "delete_blog_article", "Delete blog article"
        PUBLISH_BLOG_ARTICLE = "publish_blog_article", "Publish blog article"
        EXECUTE_SQL = "execute_sql", "Execute SQL"
        EXECUTE_MCP_TOOL = "execute_mcp_tool", "Execute MCP tool"
        EXTERNAL_DEPLOY = "external_deploy", "External deploy"
        SEND_EMAIL = "send_email", "Send email"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        EXECUTED = "executed", "Executed"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    action = models.CharField(max_length=40, choices=Action.choices)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    requester = models.CharField(max_length=80, blank=True)
    reviewer = models.CharField(max_length=80, blank=True)
    review_note = models.TextField(blank=True)
    result = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_action_display()}: {self.title}"


class MCPTool(models.Model):
    class Category(models.TextChoices):
        SYSTEM = "system", "System"
        FILESYSTEM = "filesystem", "Filesystem"
        GIT = "git", "Git"
        WEB = "web", "Web"
        DATABASE = "database", "Database"

    name = models.CharField(max_length=80, unique=True)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    display_name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=30, choices=Category.choices)
    permission_scope = models.CharField(max_length=160, blank=True)
    is_enabled = models.BooleanField(default=True)
    requires_approval = models.BooleanField(default=False)
    config = models.JSONField(default=dict, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self) -> str:
        return self.display_name
