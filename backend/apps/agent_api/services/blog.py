from __future__ import annotations

from django.utils import timezone
from django.utils.text import slugify

from ..models import ArticleCategory, ArticleTag, BlogArticle, Document
from .rag import get_default_knowledge_base, ingest_document


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


def publish_article_to_knowledge_base(article: BlogArticle) -> BlogArticle:
    knowledge_base = get_default_knowledge_base()
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

    document = ingest_document(document)
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


def serialize_category(category: ArticleCategory) -> dict:
    return {
        "id": category.id,
        "name": category.name,
        "slug": category.slug,
        "description": category.description,
        "article_count": category.articles.filter(status=BlogArticle.Status.PUBLISHED).count(),
    }


def serialize_tag(tag: ArticleTag) -> dict:
    return {
        "id": tag.id,
        "name": tag.name,
        "slug": tag.slug,
        "article_count": tag.articles.filter(status=BlogArticle.Status.PUBLISHED).count(),
    }


def serialize_article(article: BlogArticle, include_content: bool = False) -> dict:
    data = {
        "id": article.id,
        "title": article.title,
        "slug": article.slug,
        "summary": article.summary,
        "cover_image": article.cover_image or "",
        "status": article.status,
        "view_count": article.view_count,
        "category": serialize_category(article.category) if article.category else None,
        "tags": [serialize_tag(tag) for tag in article.tags.all()],
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "created_at": article.created_at.isoformat(),
        "updated_at": article.updated_at.isoformat(),
        "knowledge_document_id": article.knowledge_document_id,
        "comment_count": article.comments.filter(is_approved=True).count(),
    }
    if include_content:
        data["content"] = article.content
        data["comments"] = [
            {
                "id": comment.id,
                "author_name": comment.author_name,
                "content": comment.content,
                "created_at": comment.created_at.isoformat(),
            }
            for comment in article.comments.filter(is_approved=True)
        ]
    return data
