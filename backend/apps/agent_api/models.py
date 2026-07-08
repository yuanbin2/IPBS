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
    sources = models.JSONField(default=list, blank=True)
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
    sources = models.JSONField(default=list, blank=True)
    trace = models.JSONField(default=list, blank=True)
    token_usage = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class KnowledgeBase(models.Model):
    name = models.CharField(max_length=120, unique=True)
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
