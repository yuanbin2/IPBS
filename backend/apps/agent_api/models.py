from django.conf import settings
from django.db import models


DEFAULT_WORKSPACE_KEY = "default"


class Conversation(models.Model):
    title = models.CharField(max_length=160, blank=True)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
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
    sources = models.JSONField(default=list, blank=True)
    trace = models.JSONField(default=list, blank=True)
    token_usage = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class AgentRun(models.Model):
    conversation = models.ForeignKey(Conversation, related_name="agent_runs", on_delete=models.CASCADE)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    input_message = models.TextField()
    route = models.CharField(max_length=32, blank=True)
    tool_calls = models.JSONField(default=list, blank=True)
    sources = models.JSONField(default=list, blank=True)
    trace = models.JSONField(default=list, blank=True)
    token_usage = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class KnowledgeBase(models.Model):
    name = models.CharField(max_length=120, unique=True)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Document(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    knowledge_base = models.ForeignKey(KnowledgeBase, related_name="documents", on_delete=models.CASCADE)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    title = models.CharField(max_length=180)
    source_file = models.FileField(upload_to="knowledge/", blank=True)
    content_text = models.TextField(blank=True)
    content_type = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    error_message = models.TextField(blank=True)
    chunk_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class DocumentChunk(models.Model):
    document = models.ForeignKey(Document, related_name="chunks", on_delete=models.CASCADE)
    knowledge_base = models.ForeignKey(KnowledgeBase, related_name="chunks", on_delete=models.CASCADE)
    chunk_index = models.PositiveIntegerField()
    content = models.TextField()
    token_estimate = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["document_id", "chunk_index"]
        unique_together = [("document", "chunk_index")]

    def __str__(self) -> str:
        return f"{self.document.title} #{self.chunk_index}"


class EmbeddingRecord(models.Model):
    chunk = models.OneToOneField(DocumentChunk, related_name="embedding_record", on_delete=models.CASCADE)
    model = models.CharField(max_length=120)
    vector = models.JSONField(default=list)
    vector_dimensions = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["chunk_id"]


class ArticleCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, allow_unicode=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ArticleTag(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=80, unique=True, allow_unicode=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class BlogArticle(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    title = models.CharField(max_length=180)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    slug = models.SlugField(max_length=220, unique=True, allow_unicode=True)
    summary = models.TextField(blank=True)
    content = models.TextField()
    category = models.ForeignKey(
        ArticleCategory,
        related_name="articles",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    tags = models.ManyToManyField(ArticleTag, related_name="articles", blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    view_count = models.PositiveIntegerField(default=0)
    knowledge_document = models.ForeignKey(
        Document,
        related_name="blog_articles",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self) -> str:
        return self.title


class BlogComment(models.Model):
    article = models.ForeignKey(BlogArticle, related_name="comments", on_delete=models.CASCADE)
    author_name = models.CharField(max_length=80)
    content = models.TextField()
    is_approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class BlogAgentSession(models.Model):
    session_key = models.CharField(max_length=64, unique=True)
    visitor_label = models.CharField(max_length=80, blank=True)
    ip_hash = models.CharField(max_length=64, blank=True)
    user_agent = models.TextField(blank=True)
    is_blocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.visitor_label or self.session_key


class BlogAgentMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        AGENT = "agent", "Agent"

    session = models.ForeignKey(BlogAgentSession, related_name="messages", on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField()
    sources = models.JSONField(default=list, blank=True)
    trace = models.JSONField(default=list, blank=True)
    token_usage = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class BlogAgentSecurityEvent(models.Model):
    session = models.ForeignKey(
        BlogAgentSession,
        related_name="security_events",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    question = models.TextField()
    reason = models.CharField(max_length=160)
    ip_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ApprovalRequest(models.Model):
    class Action(models.TextChoices):
        DELETE_DOCUMENT = "delete_document", "Delete document"
        DELETE_KNOWLEDGE_BASE = "delete_knowledge_base", "Delete knowledge base"
        DELETE_BLOG_ARTICLE = "delete_blog_article", "Delete blog article"
        PUBLISH_BLOG_ARTICLE = "publish_blog_article", "Publish blog article"
        EXECUTE_SQL = "execute_sql", "Execute SQL"
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
