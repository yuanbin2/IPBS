"""Conservative cleanup for generated public blog images.

Uploads precede article saves and a URL can be reused across articles. Only
generated ``blog/<uuid>.<image extension>`` objects are eligible, and every
persisted content field that can contain a blog image is checked first.
"""

import logging
import re

from django.core.files.storage import storages
from django.db.models import Q

from ..models import (
    BlogAgentMessage,
    BlogArticle,
    BlogArticleRevision,
    BlogCollection,
    BlogCollectionNode,
    BlogComment,
    Document,
    DocumentChunk,
    PrivateNote,
)
from .blog_media import is_blog_image_name

logger = logging.getLogger(__name__)
BLOG_IMAGE_URL_RE = re.compile(r"/media/blog/([0-9a-f]{32}\.(?:png|jpg|gif|webp))(?![\w.])")


def extract_blog_image_names(*values: object) -> set[str]:
    """Accept only URLs served by this application's public image route."""
    names: set[str] = set()
    for value in values:
        if value:
            names.update(match.group(1) for match in BLOG_IMAGE_URL_RE.finditer(str(value)))
    return names


def article_image_names(article: BlogArticle) -> set[str]:
    """Snapshot the article and every revision before cascading deletion."""
    names = extract_blog_image_names(article.content, article.cover_image, article.summary)
    for content, cover_image, summary in article.revisions.values_list("content", "cover_image", "summary").iterator():
        names.update(extract_blog_image_names(content, cover_image, summary))
    return names


REFERENCE_FIELDS = (
    (BlogArticle, ("content", "cover_image", "summary")),
    (BlogArticleRevision, ("content", "cover_image", "summary")),
    (PrivateNote, ("content", "quote", "source_url")),
    (BlogCollection, ("description", "published_snapshot", "pending_snapshot")),
    (BlogCollectionNode, ("description",)),
    (BlogComment, ("content",)),
    (Document, ("content_text",)),
    (DocumentChunk, ("content",)),
    (BlogAgentMessage, ("content", "sources", "trace")),
)


def referenced_blog_image_names() -> set[str]:
    """Scan persisted user content once; on DB failure callers must not delete."""
    names: set[str] = set()
    for model, fields in REFERENCE_FIELDS:
        for row in model.objects.values_list(*fields).iterator(chunk_size=500):
            names.update(extract_blog_image_names(*row))
    return names


def is_blog_image_referenced(filename: str) -> bool:
    """Targeted lookup for deletion; avoid loading every article and RAG chunk."""
    for model, fields in REFERENCE_FIELDS:
        text_fields = [field for field in fields if model._meta.get_field(field).get_internal_type() != "JSONField"]
        if text_fields:
            predicate = Q()
            for field in text_fields:
                predicate |= Q(**{f"{field}__contains": filename})
            if model.objects.filter(predicate).exists():
                return True
        json_fields = [field for field in fields if field not in text_fields]
        if json_fields:
            for row in model.objects.values_list(*json_fields).iterator(chunk_size=500):
                if filename in str(row):
                    return True
    return False


def delete_unreferenced_blog_images(candidates: set[str]) -> list[str]:
    """Remove only candidate files with no remaining persisted references."""
    if not candidates:
        return []
    try:
        storage = storages["blog_media"]
    except Exception:
        logger.exception("Cannot open blog media storage; skipping file cleanup")
        return []

    deleted: list[str] = []
    for filename in sorted(candidates):
        if not is_blog_image_name(filename):
            continue
        try:
            if is_blog_image_referenced(filename):
                continue
            storage.delete(f"blog/{filename}")
            deleted.append(filename)
        except Exception:
            logger.exception("Cannot verify or delete blog image %s; leaving it in storage", filename)
    return deleted
