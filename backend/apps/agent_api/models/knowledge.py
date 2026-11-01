import uuid

from django.db import models

from .constants import DEFAULT_WORKSPACE_KEY


class KnowledgeBase(models.Model):
    class Category(models.TextChoices):
        TECH_DOCS = "tech_docs", "技术文档"
        PRODUCT_DOCS = "product_docs", "产品文档"
        LEARNING_NOTES = "learning_notes", "学习笔记"
        PROJECT_DOCS = "project_docs", "项目资料"
        OTHER = "other", "其他"

    name = models.CharField(max_length=120)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=30, choices=Category.choices, default=Category.OTHER, help_text="知识库分类")
    tags = models.JSONField(default=list, blank=True, help_text="标签列表，如 ['AI', 'Python', '教程']")
    is_archived = models.BooleanField(default=False, help_text="是否已归档")
    sort_order = models.IntegerField(default=0, help_text="排序顺序，数字越小越靠前")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace_key", "name"], name="unique_knowledge_base_per_workspace"),
        ]

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
    desired_ingestion_generation = models.PositiveIntegerField(default=0)
    active_ingestion_generation = models.PositiveIntegerField(default=0)
    ingestion_error_code = models.CharField(max_length=80, blank=True, default="")
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
    ingestion_generation = models.PositiveIntegerField(default=0, db_index=True)
    content = models.TextField()
    token_estimate = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["document_id", "chunk_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "ingestion_generation", "chunk_index"],
                name="unique_document_ingestion_chunk",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.document.title} #{self.chunk_index}"


class EmbeddingRecord(models.Model):
    class Status(models.TextChoices):
        READY = "ready", "Ready"
        QUARANTINED = "quarantined", "Quarantined"
        NEEDS_REINDEX = "needs_reindex", "Needs reindex"

    chunk = models.OneToOneField(DocumentChunk, related_name="embedding_record", on_delete=models.CASCADE)
    model = models.CharField(max_length=120)
    vector = models.JSONField(default=list)
    vector_dimensions = models.PositiveIntegerField(default=0)
    provider = models.CharField(max_length=120, default="legacy-unknown")
    model_version = models.CharField(max_length=120, default="unknown")
    algorithm_version = models.CharField(max_length=120, default="unknown")
    normalized = models.BooleanField(default=False)
    corpus_version = models.CharField(max_length=120, default="unknown")
    index_version = models.CharField(max_length=120, default="unknown")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.QUARANTINED, db_index=True)
    fallback_reason = models.CharField(max_length=160, blank=True, default="")
    embedded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["chunk_id"]


class DocumentIngestionJob(models.Model):
    """Durable outbox entry and idempotency boundary for one index generation."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending dispatch"
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        RETRY = "retry", "Retry scheduled"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        SUPERSEDED = "superseded", "Superseded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_id = models.CharField(max_length=36, blank=True, default="", db_index=True)
    document = models.ForeignKey(Document, related_name="ingestion_jobs", on_delete=models.CASCADE)
    generation = models.PositiveIntegerField()
    content_version = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=180, unique=True)
    title_snapshot = models.CharField(max_length=180)
    content_text_snapshot = models.TextField(blank=True)
    content_type_snapshot = models.CharField(max_length=120, blank=True)
    source_file_name = models.CharField(max_length=500, blank=True)
    workspace_key = models.CharField(max_length=80)
    knowledge_base_id = models.PositiveBigIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    failure_code = models.CharField(max_length=100, blank=True, default="")
    failure_message = models.CharField(max_length=300, blank=True, default="")
    timings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["document", "generation"], name="unique_document_ingestion_generation"),
        ]
        indexes = [models.Index(fields=["status", "next_attempt_at"], name="ingestion_due_jobs_idx")]
