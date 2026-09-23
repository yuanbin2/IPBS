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
    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        default=Category.OTHER,
        help_text="知识库分类"
    )
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text="标签列表，如 ['AI', 'Python', '教程']"
    )
    is_archived = models.BooleanField(
        default=False,
        help_text="是否已归档"
    )
    sort_order = models.IntegerField(
        default=0,
        help_text="排序顺序，数字越小越靠前"
    )
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
