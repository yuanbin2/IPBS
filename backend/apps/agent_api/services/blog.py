from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from ..models import ArticleCategory, ArticleTag, BlogArticle, BlogArticleRevision, Document
from .ingestion_jobs import schedule_document_ingestion
from .rag import get_default_knowledge_base

ARTICLE_LIST_LIMIT = 50

# 正文图片既可能是 Markdown 语法，也可能是富文本编辑器留下的 <img>。
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*<?([^\s)>]+)>?")
_HTML_IMAGE_RE = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_UNSAFE_URL_PREFIXES = ("javascript:", "vbscript:", "data:", "file:")
_MAX_COVER_URL_LENGTH = 2048


class ArticleAccessError(Exception):
    """调用方无权以当前身份查看请求的文章列表（如未登录查看草稿）。"""


def article_publication_fingerprint(article: BlogArticle) -> str:
    """Bind a publish approval to the exact article content being reviewed."""
    snapshot = {
        "title": article.title,
        "summary": article.summary,
        "cover_image": article.cover_image,
        "content": article.content,
        "category_id": article.category_id,
        "tags": list(article.tags.order_by("pk").values_list("pk", flat=True)),
        "status": article.status,
        "publication_version": article.publication_version,
    }
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass
class ArticleListFilters:
    """博客列表的查询参数白名单，由 View 从 query_params 解析后传入。"""

    status: str = BlogArticle.Status.PUBLISHED
    category_slug: str = ""
    tag_slug: str = ""
    query: str = ""
    author_name: str = ""
    my_only: bool = False


def list_articles(
    filters: ArticleListFilters,
    *,
    workspace_key: str,
    actor: str,
    authenticated: bool,
    is_admin: bool,
) -> list[BlogArticle]:
    """按过滤器返回文章列表：草稿/拒绝态仅登录可见，非管理员只能看自己的。"""
    articles = filtered_articles(
        filters,
        workspace_key=workspace_key,
        actor=actor,
        authenticated=authenticated,
        is_admin=is_admin,
    )
    return list(articles[:ARTICLE_LIST_LIMIT])


def filtered_articles(
    filters: ArticleListFilters,
    *,
    workspace_key: str,
    actor: str,
    authenticated: bool,
    is_admin: bool,
):
    """Share the workspace and draft authorization boundary with paginated discovery."""
    articles = (
        BlogArticle.objects.select_related("category", "knowledge_document")
        .prefetch_related("tags")
        .filter(workspace_key=workspace_key)
    )
    if filters.status != "all":
        articles = articles.filter(status=filters.status)

    if filters.status in {BlogArticle.Status.DRAFT, BlogArticle.Status.REJECTED}:
        if not authenticated:
            raise ArticleAccessError("请先登录")
        if not is_admin:
            # 普通用户只能看到自己提交的（忽略大小写）
            articles = articles.filter(author_name__iexact=actor)
    elif filters.status == "all":
        if not authenticated:
            articles = articles.filter(status=BlogArticle.Status.PUBLISHED)
        elif not is_admin:
            articles = articles.filter(Q(status=BlogArticle.Status.PUBLISHED) | Q(author_name__iexact=actor))
    else:
        # 已发布文章，支持按 author_name 过滤（忽略大小写）
        if filters.author_name:
            articles = articles.filter(author_name__iexact=filters.author_name)
        elif authenticated and not is_admin and filters.my_only:
            articles = articles.filter(author_name__iexact=actor)

    if filters.category_slug:
        articles = articles.filter(category__slug=filters.category_slug)
    if filters.tag_slug:
        articles = articles.filter(tags__slug=filters.tag_slug)
    if filters.query:
        articles = articles.filter(
            Q(title__icontains=filters.query)
            | Q(summary__icontains=filters.query)
            | Q(content__icontains=filters.query)
        )

    return articles.distinct()


def unique_slug(model, value: str, instance_id: int | None = None, max_length: int = 180) -> str:
    base = slugify(value, allow_unicode=True)[:max_length].strip("-") or "article"
    slug = base
    suffix = 2
    queryset = model.objects.all()
    if instance_id:
        queryset = queryset.exclude(pk=instance_id)
    while queryset.filter(slug=slug).exists():
        suffix_text = f"-{suffix}"
        slug = f"{base[: max_length - len(suffix_text)]}{suffix_text}"
        suffix += 1
    return slug


def get_or_create_category(name: str | None) -> ArticleCategory | None:
    if not name:
        return None
    clean_name = name.strip()
    if not clean_name:
        return None
    category, _ = ArticleCategory.objects.get_or_create(
        name=clean_name,
        defaults={"slug": unique_slug(ArticleCategory, clean_name, max_length=90)},
    )
    return category


def set_article_tags(article: BlogArticle, tag_names: list[str]) -> None:
    tags = []
    for name in tag_names:
        clean_name = str(name).strip()
        if not clean_name:
            continue
        tag, _ = ArticleTag.objects.get_or_create(
            name=clean_name,
            defaults={"slug": unique_slug(ArticleTag, clean_name, max_length=70)},
        )
        tags.append(tag)
    article.tags.set(tags)


def is_safe_image_url(url: str) -> bool:
    """只接受 http(s) 绝对地址与站内相对路径，挡掉 javascript:/data: 之类。"""
    if not url or len(url) > _MAX_COVER_URL_LENGTH:
        return False
    lowered = url.strip().lower()
    if lowered.startswith(_UNSAFE_URL_PREFIXES):
        return False
    return lowered.startswith(("http://", "https://", "/", "./", "../"))


def first_image_url(content: str) -> str | None:
    """正文里出现的第一张图片链接；Markdown 与 <img> 按位置竞争，data: URI 跳过。"""
    if not content:
        return None
    candidates: list[tuple[int, str]] = []
    for pattern in (_MARKDOWN_IMAGE_RE, _HTML_IMAGE_RE):
        for match in pattern.finditer(content):
            candidates.append((match.start(1), match.group(1)))
    candidates.sort(key=lambda item: item[0])
    for _position, raw in candidates:
        url = raw.strip().strip("\"'").strip()
        if not is_safe_image_url(url):
            continue
        return url
    return None


def fill_default_cover(target: BlogArticle | BlogArticleRevision) -> str | None:
    """未填封面时用正文第一张图片兜底；返回补上的链接，没补返回 None。"""
    if (target.cover_image or "").strip():
        return None
    url = first_image_url(target.content or "")
    if not url:
        return None
    target.cover_image = url
    return url


@transaction.atomic
def publish_article_to_knowledge_base(article: BlogArticle) -> BlogArticle:
    knowledge_base = get_default_knowledge_base(article.workspace_key)
    document = article.knowledge_document
    content = article_to_knowledge_text(article)

    if document is None:
        document = Document.objects.create(
            knowledge_base=knowledge_base,
            title=f"博客：{article.title}",
            content_text=content,
            content_type="text/markdown",
        )
    else:
        document.knowledge_base = knowledge_base
        document.title = f"博客：{article.title}"
        document.content_text = content
        document.content_type = "text/markdown"
        document.save(update_fields=["knowledge_base", "title", "content_text", "content_type", "updated_at"])

    document.workspace_key = article.workspace_key
    document.save(update_fields=["workspace_key", "updated_at"])
    schedule_document_ingestion(document)
    article.knowledge_document = document
    if article.status != BlogArticle.Status.PUBLISHED:
        article.status = BlogArticle.Status.PUBLISHED
    if article.published_at is None:
        article.published_at = timezone.now()
    article.save(update_fields=["knowledge_document", "status", "published_at", "updated_at"])
    return article


def article_to_knowledge_text(article: BlogArticle) -> str:
    tags = "、".join(tag.name for tag in article.tags.all())
    category = article.category.name if article.category else "未分类"
    return "\n\n".join(
        [
            f"# {article.title}",
            f"分类：{category}",
            f"标签：{tags or '无'}",
            f"摘要：{article.summary or '无'}",
            article.content,
        ]
    )
