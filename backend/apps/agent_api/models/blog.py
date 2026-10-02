from django.conf import settings
from django.db import models

from .constants import DEFAULT_WORKSPACE_KEY
from .knowledge import Document


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
        REJECTED = "rejected", "Rejected"

    title = models.CharField(max_length=180)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    slug = models.SlugField(max_length=220, unique=True, allow_unicode=True)
    author_name = models.CharField(max_length=80, blank=True, default="")
    summary = models.TextField(blank=True)
    cover_image = models.TextField(blank=True, default="")
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
    publication_version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self) -> str:
        return self.title


class BlogArticleRevision(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        SUPERSEDED = "superseded", "Superseded"

    article = models.ForeignKey(BlogArticle, related_name="revisions", on_delete=models.CASCADE)
    base_version = models.PositiveIntegerField()
    title = models.CharField(max_length=180)
    summary = models.TextField(blank=True)
    cover_image = models.TextField(blank=True)
    content = models.TextField()
    category = models.ForeignKey(ArticleCategory, on_delete=models.SET_NULL, null=True, blank=True)
    tags = models.JSONField(default=list)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    submitted_by = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class PrivateNote(models.Model):
    """A user's private reading note, separate from publication and RAG."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="private_notes", on_delete=models.CASCADE)
    workspace_key = models.CharField(max_length=80, db_index=True)
    source_article = models.ForeignKey(
        BlogArticle,
        related_name="private_notes",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=180)
    content = models.TextField(blank=True)
    quote = models.TextField(blank=True)
    anchor_offset = models.PositiveIntegerField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [models.Index(fields=["workspace_key", "owner", "deleted_at", "-updated_at"])]


class BlogComment(models.Model):
    article = models.ForeignKey(BlogArticle, related_name="comments", on_delete=models.CASCADE)
    author_name = models.CharField(max_length=80)
    content = models.TextField()
    quote = models.TextField(blank=True)
    anchor_offset = models.PositiveIntegerField(null=True, blank=True)
    is_approved = models.BooleanField(default=False)
    is_reviewed = models.BooleanField(default=False)
    reviewed_by = models.CharField(max_length=120, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class BlogCommentReport(models.Model):
    class Reason(models.TextChoices):
        SPAM = "spam", "Spam"
        ABUSE = "abuse", "Abuse"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        HIDDEN = "hidden", "Comment hidden"
        DISMISSED = "dismissed", "Dismissed"

    comment = models.ForeignKey(BlogComment, related_name="reports", on_delete=models.CASCADE)
    reporter_name = models.CharField(max_length=150)
    reason = models.CharField(max_length=20, choices=Reason.choices)
    detail = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    reviewed_by = models.CharField(max_length=120, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["comment", "reporter_name"], name="unique_blog_comment_reporter")
        ]
        ordering = ["-created_at"]


class BlogInteractionRestriction(models.Model):
    class AppealStatus(models.TextChoices):
        NONE = "none", "No appeal"
        PENDING = "pending", "Pending"
        UPHELD = "upheld", "Upheld"
        ACCEPTED = "accepted", "Accepted"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="blog_restrictions", on_delete=models.CASCADE)
    workspace_key = models.CharField(max_length=80, db_index=True)
    reason = models.CharField(max_length=500)
    expires_at = models.DateTimeField()
    imposed_by = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    lifted_at = models.DateTimeField(null=True, blank=True)
    lifted_by = models.CharField(max_length=120, blank=True)
    appeal_message = models.CharField(max_length=1000, blank=True)
    appealed_at = models.DateTimeField(null=True, blank=True)
    appeal_status = models.CharField(max_length=20, choices=AppealStatus.choices, default=AppealStatus.NONE)
    appeal_reviewed_by = models.CharField(max_length=120, blank=True)
    appeal_reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["workspace_key", "user", "expires_at"])]


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
