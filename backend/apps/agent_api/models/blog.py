import uuid

from django.conf import settings
from django.db import models

from .constants import DEFAULT_WORKSPACE_KEY
from .governance import ApprovalRequest
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
    # 外部网页剪藏来源（B-043）：与本站文章来源 source_article 互斥，二者可同时为空。
    source_url = models.TextField(blank=True, default="", null=True)
    source_title = models.CharField(max_length=200, blank=True, default="")
    captured_at = models.DateTimeField(null=True, blank=True)
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


class BlogCollection(models.Model):
    """领域目录：作者私有的课程/章节/知识点树，审核后以不可变快照公开。"""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="blog_collections", on_delete=models.CASCADE)
    workspace_key = models.CharField(max_length=80, default=DEFAULT_WORKSPACE_KEY, db_index=True)
    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, allow_unicode=True)
    description = models.TextField(blank=True)
    draft_version = models.PositiveIntegerField(default=1)
    publication_version = models.PositiveIntegerField(default=0)
    published_snapshot = models.JSONField(null=True, blank=True)
    pending_snapshot = models.JSONField(null=True, blank=True)
    pending_approval = models.ForeignKey(
        ApprovalRequest,
        related_name="blog_collections",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["workspace_key", "owner", "slug"], name="unique_blog_collection_owner_slug")
        ]
        indexes = [models.Index(fields=["workspace_key", "owner", "archived_at"])]

    def __str__(self) -> str:
        return self.title


class BlogCollectionNode(models.Model):
    """目录节点：parent 邻接表，根下最多三级；删除/移动只作用于私有工作版。"""

    collection = models.ForeignKey(BlogCollection, related_name="nodes", on_delete=models.CASCADE)
    parent = models.ForeignKey("self", related_name="children", on_delete=models.CASCADE, null=True, blank=True)
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        indexes = [models.Index(fields=["collection", "parent", "position"])]

    def __str__(self) -> str:
        return self.title


class BlogCollectionEntry(models.Model):
    """目录内文章引用：node 为空表示直接挂领域根；同领域一篇文章只出现一次。"""

    collection = models.ForeignKey(BlogCollection, related_name="entries", on_delete=models.CASCADE)
    node = models.ForeignKey(
        BlogCollectionNode, related_name="entries", on_delete=models.CASCADE, null=True, blank=True
    )
    article = models.ForeignKey(BlogArticle, related_name="collection_entries", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [models.UniqueConstraint(fields=["collection", "article"], name="unique_blog_collection_article")]
        indexes = [models.Index(fields=["collection", "node", "position"])]

    def __str__(self) -> str:
        return f"{self.collection_id}:{self.article_id}"


class BlogCollectionAutoRule(models.Model):
    """领域自动收录规则：命中的已发布文章自动挂到指定节点（B-065）。

    node 为空表示挂领域根；category 必填，tag 为空表示不限制标签。
    规则只影响私有工作版，不进入公开快照；应用是幂等的补齐操作。
    """

    collection = models.ForeignKey(BlogCollection, related_name="auto_rules", on_delete=models.CASCADE)
    node = models.ForeignKey(
        BlogCollectionNode,
        related_name="auto_rules",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    category = models.ForeignKey(
        ArticleCategory, related_name="collection_auto_rules", on_delete=models.CASCADE, null=True, blank=True
    )
    tag = models.ForeignKey(
        ArticleTag, related_name="collection_auto_rules", on_delete=models.CASCADE, null=True, blank=True
    )
    enabled = models.BooleanField(default=True)
    last_applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["collection", "enabled"])]

    def __str__(self) -> str:
        target = self.node.title if self.node_id else "领域根"
        category = self.category.name if self.category_id else "全部分类"
        tag = f" #{self.tag.name}" if self.tag_id else ""
        return f"{category}{tag} → {target}"


class PrivateNoteImage(models.Model):
    """私有笔记配图：不公开的对象键 + owner/workspace 鉴权读取。

    与公开 blog_media 完全隔离：绝不以 /media/... 公开地址出现。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="private_note_images", on_delete=models.CASCADE)
    workspace_key = models.CharField(max_length=80, db_index=True)
    # 图片可先于笔记存在（剪藏时逐张确认），保存笔记时再绑定
    note = models.ForeignKey(
        PrivateNote,
        related_name="images",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    file = models.FileField(upload_to="private-notes/%Y/%m/", max_length=300)
    original_name = models.CharField(max_length=200, blank=True, default="")
    source_url = models.TextField(blank=True, default="")
    byte_size = models.PositiveIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["workspace_key", "owner", "note"])]


class BlogSetting(models.Model):
    """站点级设置（单例行）：设置页编辑，公开页面读取。

    与用户/工作区无关——这些值描述整个博客站点，只有管理员能改。
    """

    site_title = models.CharField(max_length=120, blank=True, default="")
    site_tagline = models.CharField(max_length=200, blank=True, default="")
    author_name = models.CharField(max_length=80, blank=True, default="")
    about_title = models.CharField(max_length=120, blank=True, default="")
    about_content = models.TextField(blank=True, default="")
    about_highlights = models.JSONField(default=list, blank=True)
    footer_text = models.CharField(max_length=200, blank=True, default="")
    articles_per_page = models.PositiveIntegerField(default=12)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "站点设置"
        verbose_name_plural = "站点设置"

    def save(self, *args, **kwargs):
        # 单例：始终写主键 1
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        # 首页会并行请求 settings/about；首次读取时让 get_or_create 处理并发插入。
        return cls.objects.get_or_create(pk=1)[0]

    def __str__(self):
        return "站点设置"
