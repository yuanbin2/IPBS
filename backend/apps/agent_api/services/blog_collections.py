"""领域目录（B-042）服务层：树校验、快照与公开读取的纯逻辑。

目录是博客的组织层，不是 RAG KnowledgeBase；公开读取只解析
同 workspace、当前仍为 published 的文章。
"""

from __future__ import annotations

import hashlib
import json
import re

from django.utils import timezone

from ..models import (
    ArticleCategory,
    ArticleTag,
    BlogArticle,
    BlogCollection,
    BlogCollectionAutoRule,
    BlogCollectionEntry,
    BlogCollectionNode,
)

MAX_COLLECTION_TITLE = 120
MAX_DESCRIPTION = 500
MAX_NODE_TITLE = 120
MAX_NODES = 100
MAX_ENTRIES = 500
MAX_DEPTH = 3
MAX_SEARCH_QUERY = 100
SNAPSHOT_VERSION = "collection-snapshot-v1"

_SLUG_CLEAN = re.compile(r"[^\w-]+", re.UNICODE)


class CollectionError(ValueError):
    def __init__(self, detail: str, *, code: str = "validation_error", http_status: int = 400):
        super().__init__(detail)
        self.code = code
        self.http_status = http_status


def clean_text(value, *, field: str, max_length: int, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise CollectionError(f"{field} 必须是字符串")
    text = re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()
    if required and not text:
        raise CollectionError(f"{field} 不能为空")
    if len(text) > max_length:
        raise CollectionError(f"{field} 不能超过 {max_length} 个字符")
    return text


def collection_slug(title: str) -> str:
    slug = _SLUG_CLEAN.sub("-", title.strip().lower()).strip("-")[:120] or "collection"
    return slug


def node_depth(node: BlogCollectionNode) -> int:
    """Depth below the collection root: a root-level node is depth 1."""
    depth = 1
    current = node
    seen = {current.pk}
    while current.parent_id is not None:
        current = current.parent
        if current.pk in seen:  # pragma: no cover - cycles are rejected before save
            raise CollectionError("目录节点出现环")
        seen.add(current.pk)
        depth += 1
    return depth


def subtree_depth(node: BlogCollectionNode) -> int:
    """Height of the subtree rooted at node (a leaf is 1)."""
    children = list(node.children.all())
    if not children:
        return 1
    return 1 + max(subtree_depth(child) for child in children)


def ensure_parent_in_collection(collection: BlogCollection, parent_id) -> BlogCollectionNode | None:
    if parent_id in (None, "", 0):
        return None
    try:
        parent = collection.nodes.get(pk=int(parent_id))
    except (BlogCollectionNode.DoesNotExist, TypeError, ValueError):
        raise CollectionError("父节点不存在或不属于该领域") from None
    return parent


def ensure_move_target(collection: BlogCollection, node: BlogCollectionNode, parent: BlogCollectionNode | None) -> None:
    if parent is None:
        return
    if parent.collection_id != collection.pk:
        raise CollectionError("不能移动到其他领域的节点下")
    ancestor = parent
    seen = {node.pk}
    while ancestor is not None:
        if ancestor.pk in seen:
            raise CollectionError("不能把节点移动到自己或自己的子节点下")
        seen.add(ancestor.pk)
        ancestor = ancestor.parent


def ensure_depth_ok(
    collection: BlogCollection, node: BlogCollectionNode, new_parent: BlogCollectionNode | None
) -> None:
    """Validate final depth (≤ MAX_DEPTH) when node gets new_parent (may be current)."""
    if new_parent is None:
        ancestors = 0
    else:
        ancestors = 0
        current: BlogCollectionNode | None = new_parent
        while current is not None:
            ancestors += 1
            current = current.parent
    height = 1 if node.pk is None else subtree_depth(node)
    if ancestors + height > MAX_DEPTH:
        raise CollectionError(f"目录层级最多 {MAX_DEPTH} 级，请把内容拆到其他领域或节点")


def ensure_node_capacity(collection: BlogCollection) -> None:
    if collection.nodes.count() >= MAX_NODES:
        raise CollectionError(f"单个领域最多 {MAX_NODES} 个目录节点")


def ensure_entry_capacity(collection: BlogCollection) -> None:
    if collection.entries.count() >= MAX_ENTRIES:
        raise CollectionError(f"单个领域最多收录 {MAX_ENTRIES} 篇文章")


def get_entry_article(collection: BlogCollection, article_id) -> BlogArticle:
    try:
        article_id = int(article_id)
    except (TypeError, ValueError):
        raise CollectionError("文章 ID 无效") from None
    try:
        article = BlogArticle.objects.get(pk=article_id, workspace_key=collection.workspace_key)
    except BlogArticle.DoesNotExist:
        raise CollectionError("文章不存在或不属于当前工作区") from None
    if article.status != BlogArticle.Status.PUBLISHED:
        raise CollectionError("只能收录已发布的文章")
    return article


def reorder_ids_match(current_ids: list[int], ordered_ids) -> list[int]:
    if not isinstance(ordered_ids, list) or any(not isinstance(item, int) for item in ordered_ids):
        raise CollectionError("顺序列表无效")
    if len(ordered_ids) > MAX_ENTRIES or len(ordered_ids) > max(len(current_ids), 0):
        raise CollectionError("顺序列表无效")
    if sorted(ordered_ids) != sorted(current_ids):
        raise CollectionError("顺序列表必须恰好包含当前节点的全部 ID")
    return ordered_ids


def build_snapshot(collection: BlogCollection) -> dict:
    """Freeze the draft tree into the reviewable, plain-text snapshot format."""
    nodes = [
        {
            "id": node.id,
            "parent": node.parent_id,
            "title": node.title,
            "description": node.description,
            "position": node.position,
        }
        for node in collection.nodes.all()
    ]
    entries = [
        {"id": entry.id, "node": entry.node_id, "article": entry.article_id, "position": entry.position}
        for entry in collection.entries.all()
    ]
    return {
        "format": SNAPSHOT_VERSION,
        "title": collection.title,
        "description": collection.description,
        "draft_version": collection.draft_version,
        "nodes": nodes,
        "entries": entries,
    }


def snapshot_sha256(snapshot: dict) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def serialize_collection_summary(collection: BlogCollection) -> dict:
    return {
        "public_id": str(collection.public_id),
        "title": collection.title,
        "slug": collection.slug,
        "description": collection.description,
        "draft_version": collection.draft_version,
        "publication_version": collection.publication_version,
        "has_pending": bool(collection.pending_approval_id),
        "pending_approval_id": collection.pending_approval_id,
        "is_published": bool(collection.published_snapshot),
        "archived_at": collection.archived_at.isoformat() if collection.archived_at else None,
        "created_at": collection.created_at.isoformat(),
        "updated_at": collection.updated_at.isoformat(),
    }


def serialize_auto_rule(rule: BlogCollectionAutoRule) -> dict:
    node_title = rule.node.title if rule.node_id else ""
    return {
        "id": rule.id,
        "node": rule.node_id,
        "node_title": node_title,
        "node_label": node_title or "领域根",
        "category": (
            {"id": rule.category_id, "name": rule.category.name, "slug": rule.category.slug}
            if rule.category_id and rule.category
            else None
        ),
        "tag": ({"id": rule.tag_id, "name": rule.tag.name} if rule.tag_id and rule.tag else None),
        "enabled": bool(rule.enabled),
        "last_applied_at": rule.last_applied_at.isoformat() if rule.last_applied_at else None,
        "created_at": rule.created_at.isoformat(),
    }


def resolve_auto_rule_targets(
    collection: BlogCollection,
    node_id,
    category_id=None,
    category_slug=None,
    tag_id=None,
) -> tuple[BlogCollectionNode | None, ArticleCategory, ArticleTag | None]:
    """Validate rule targets belong to the same collection / global taxonomies."""
    node = None
    if node_id not in (None, "", 0):
        try:
            node_pk = int(node_id)
        except (TypeError, ValueError):
            raise CollectionError("节点 ID 无效") from None
        node = ensure_parent_in_collection(collection, node_pk)

    category = None
    if category_id not in (None, ""):
        try:
            category = ArticleCategory.objects.filter(pk=int(category_id)).first()
        except (TypeError, ValueError):
            category = None
    elif category_slug:
        category = ArticleCategory.objects.filter(slug=str(category_slug)).first()
    if category is None:
        raise CollectionError("请选择一个分类作为自动收录条件")

    tag = None
    if tag_id not in (None, ""):
        try:
            tag = ArticleTag.objects.filter(pk=int(tag_id)).first()
        except (TypeError, ValueError):
            raise CollectionError("标签 ID 无效") from None
        if tag is None:
            raise CollectionError("标签不存在")
    return node, category, tag


def matching_articles_for_rule(collection: BlogCollection, rule: BlogCollectionAutoRule, exclude_ids):
    """Published, same-workspace articles matching the rule that are not collected yet."""
    queryset = BlogArticle.objects.filter(
        workspace_key=collection.workspace_key, status=BlogArticle.Status.PUBLISHED
    )
    if rule.category_id:
        queryset = queryset.filter(category_id=rule.category_id)
    if rule.tag_id:
        queryset = queryset.filter(tags__id=rule.tag_id)
    return queryset.exclude(pk__in=list(exclude_ids)).distinct().order_by("published_at", "id")


def apply_auto_rules(collection: BlogCollection, *, enabled_only: bool = True) -> dict:
    """Idempotently collect new articles matching enabled rules.

    Returns {"added": int, "rules": int}; bumps draft_version when anything is added.
    """
    rules = list(collection.auto_rules.select_related("node", "category", "tag").all())
    if enabled_only:
        rules = [rule for rule in rules if rule.enabled]
    if not rules:
        return {"added": 0, "rules": 0}

    known_ids = set(collection.entries.values_list("article_id", flat=True))
    total = len(known_ids)
    added = 0
    now = timezone.now()
    for rule in rules:
        position_base = collection.entries.filter(node=rule.node).count()
        offset = 0
        for article in matching_articles_for_rule(collection, rule, known_ids):
            if total >= MAX_ENTRIES:
                break
            BlogCollectionEntry.objects.create(
                collection=collection, node=rule.node, article=article, position=position_base + offset
            )
            known_ids.add(article.pk)
            total += 1
            added += 1
            offset += 1
        rule.last_applied_at = now
        rule.save(update_fields=["last_applied_at"])
    if added:
        collection.draft_version += 1
        collection.save(update_fields=["draft_version", "updated_at"])
    return {"added": added, "rules": len(rules)}


def serialize_draft_tree(collection: BlogCollection, *, include_articles: bool = True) -> dict:
    data = serialize_collection_summary(collection)
    data["auto_rules"] = [serialize_auto_rule(rule) for rule in collection.auto_rules.all()]
    data["nodes"] = [
        {
            "id": node.id,
            "parent": node.parent_id,
            "title": node.title,
            "description": node.description,
            "position": node.position,
        }
        for node in collection.nodes.all()
    ]
    entries = list(collection.entries.select_related("article", "node").all())
    data["entries"] = (
        [
            {
                "id": entry.id,
                "node": entry.node_id,
                "position": entry.position,
                "article": {
                    "id": entry.article_id,
                    "title": entry.article.title,
                    "slug": entry.article.slug,
                    "author_name": entry.article.author_name,
                    "summary": entry.article.summary,
                    "status": entry.article.status,
                    "cover_image": entry.article.cover_image,
                },
            }
            for entry in entries
        ]
        if include_articles
        else []
    )
    return data


def published_visible_articles(workspace_key: str, article_ids: list[int]) -> dict[int, BlogArticle]:
    """One batched query: only current published, same-workspace articles resolve."""
    ids = [int(article_id) for article_id in article_ids]
    if not ids:
        return {}
    articles = BlogArticle.objects.filter(
        pk__in=ids, workspace_key=workspace_key, status=BlogArticle.Status.PUBLISHED
    ).select_related("category").prefetch_related("tags")
    return {article.pk: article for article in articles}


def serialize_public_article(article: BlogArticle) -> dict:
    return {
        "id": article.pk,
        "title": article.title,
        "slug": article.slug,
        "author_name": article.author_name,
        "summary": article.summary,
        "cover_image": article.cover_image,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        # 领域页需要按标签筛选并展示，因此把标签名与分类一并返回。
        "tags": [tag.name for tag in article.tags.all()],
        "category": article.category.name if article.category else "",
    }


def collection_reading_sequence(snapshot: dict) -> list[dict]:
    """Depth-first reading order: root entries, then each node's entries, then children."""
    children: dict[int | None, list[dict]] = {}
    for node in snapshot.get("nodes", []):
        children.setdefault(node["parent"], []).append(node)
    for bucket in children.values():
        bucket.sort(key=lambda item: (item["position"], item["id"]))
    entries_by_node: dict[int | None, list[dict]] = {}
    for entry in snapshot.get("entries", []):
        entries_by_node.setdefault(entry["node"], []).append(entry)
    for bucket in entries_by_node.values():
        bucket.sort(key=lambda item: (item["position"], item["id"]))

    sequence: list[dict] = []

    def visit(node_id: int | None, path: list[dict]) -> None:
        for entry in entries_by_node.get(node_id, []):
            sequence.append({"entry": entry, "path": list(path)})
        for node in children.get(node_id, []):
            visit(node["id"], [*path, node])

    visit(None, [])
    return sequence
