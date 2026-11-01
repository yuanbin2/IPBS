"""领域目录归档（B-067）：导出为 zip（含图片）与从 zip 导入。

导出包是自描述的可迁移格式，磁盘布局::

    manifest.json          权威元数据（领域/节点树/条目/文章索引）
    README.md              人类可读说明与目录树
    <领域slug>/
        articles/<序号>-<文章slug>.md   front-matter + 正文（图片链接指向 ../images/）
        images/<32位hex>.<ext>          正文实际引用的本站图片

``articles/`` 与 ``images/`` 是同级目录，所以正文里的 ``/media/blog/<name>``
改写成 **相对文章文件** 的 ``../images/<name>``（不是 ``images/<name>``，
否则解压后 Markdown 阅读器会去 articles/images/ 找图而显示不出来）。
manifest.json 里的 cover_image 保留原始站内路径 ``/media/blog/<name>``，
它是给导入程序读的元数据，不参与相对路径解析。
导入时两种写法都会还原为 ``/media/blog/<name>``。
外链图片（http(s)）不属于本站文件，不打包，原样保留。
"""

from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from datetime import datetime

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.utils import timezone
from django.utils.text import slugify

from ..models import (
    ArticleCategory,
    ArticleTag,
    BlogArticle,
    BlogCollection,
    BlogCollectionAutoRule,
    BlogCollectionEntry,
    BlogCollectionNode,
)
from .blog_media import MAX_IMAGE_BYTES, is_blog_image_name, validate_blog_image

ARCHIVE_FORMAT = "blog-collection-archive"
ARCHIVE_VERSION = 1
MANIFEST_NAME = "manifest.json"
README_NAME = "README.md"
ARTICLE_DIR = "articles"
IMAGE_DIR = "images"
# articles/ 与 images/ 同级：文章 md 里的图片链接必须回退一级。
ARTICLE_IMAGE_PREFIX = "../images/"

# 导入侧防护：压缩包本身与解压后的总体规模都要设上限。
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_ARCHIVE_FILES = 2000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_UNCOMPRESSED_RATIO = 200

CONFLICT_SKIP = "skip"
CONFLICT_REPLACE = "replace"
CONFLICT_RENAME = "rename"
CONFLICT_CHOICES = (CONFLICT_SKIP, CONFLICT_REPLACE, CONFLICT_RENAME)

# 正文里既可能是站内相对路径，也可能是编辑器写入的绝对地址（含域名端口），
# 两种形态都要能识别并归一成包内相对路径。
MEDIA_IMAGE_RE = re.compile(
    r"(?:https?://[^\s/)]+)?/media/blog/([0-9a-f]{32}\.(?:png|jpg|gif|webp))(?![\w.])"
)
ARCHIVE_IMAGE_RE = re.compile(
    r"(?:https?://[^\s/)]+)?(?:\.\./|\./)?(?:images/|/media/blog/)?"
    r"([0-9a-f]{32}\.(?:png|jpg|gif|webp))(?![\w.])"
)
REMOTE_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")
_SEGMENT_CLEAN = re.compile(r"[^\w一-鿿-]+", re.UNICODE)


class ArchiveError(ValueError):
    def __init__(self, detail: str, *, code: str = "validation_error", http_status: int = 400):
        super().__init__(detail)
        self.code = code
        self.http_status = http_status


def safe_segment(value: str, *, fallback: str = "item") -> str:
    """把任意标题/slug 变成安全的单层路径片段（防目录穿越）。"""
    cleaned = _SEGMENT_CLEAN.sub("-", str(value or "").strip()).strip("-")
    return (cleaned[:80] or fallback)


# --------------------------------------------------------------------------- 导出


def extract_media_image_names(*values: object) -> set[str]:
    """取出文本里由本站托管的图片文件名。"""
    names: set[str] = set()
    for value in values:
        if value:
            names.update(match.group(1) for match in MEDIA_IMAGE_RE.finditer(str(value)))
    return names


def rewrite_to_archive(text: str, *, prefix: str = ARTICLE_IMAGE_PREFIX) -> str:
    """正文里的站内图片链接改写成包内相对路径。

    文章 md 位于 ``<领域>/articles/``、图片位于 ``<领域>/images/``，两者同级，
    所以默认是 ``../images/``；README 等根目录文件可显式传 ``<领域>/images/``。
    """
    if not text:
        return text or ""
    return MEDIA_IMAGE_RE.sub(lambda match: f"{prefix}{match.group(1)}", text)


def count_remote_images(text: str) -> int:
    """正文里无法打包的外链图片数量（写进 README 提醒迁移者）。"""
    return sum(1 for url in REMOTE_IMAGE_RE.findall(text or "") if "/media/blog/" not in url)


def _yaml_scalar(value: object) -> str:
    text = "" if value is None else str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")
    return f'"{escaped}"'


def render_front_matter(data: dict) -> str:
    """最小可用 YAML front-matter 序列化：只支持标量字符串与字符串列表。"""
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def article_markdown(article: BlogArticle, *, path_prefix: str = "") -> str:
    meta = {
        "title": article.title,
        "slug": article.slug,
        "author": article.author_name,
        "category": article.category.name if article.category_id else "",
        "tags": [tag.name for tag in article.tags.all()],
        "status": article.status,
        "summary": article.summary,
        "cover": rewrite_to_archive(article.cover_image),
        "created_at": article.created_at.isoformat() if article.created_at else "",
        "updated_at": article.updated_at.isoformat() if article.updated_at else "",
    }
    body = rewrite_to_archive(article.content or "")
    return f"{render_front_matter(meta)}\n\n{body}\n"


def serialize_collection_export(collection: BlogCollection) -> dict:
    """把一个领域整理成清单条目 + 需要写入包内的文件（纯数据，不碰文件系统）。"""
    nodes = [
        {
            "ref": node.id,
            "parent_ref": node.parent_id,
            "title": node.title,
            "description": node.description,
            "position": node.position,
        }
        for node in collection.nodes.all().order_by("position", "id")
    ]
    entries = [
        {"node_ref": entry.node_id, "article_slug": entry.article.slug, "position": entry.position}
        for entry in collection.entries.select_related("article").all().order_by("position", "id")
    ]
    rules = [
        {
            "node_ref": rule.node_id,
            "category": rule.category.name if rule.category_id else "",
            "tag": rule.tag.name if rule.tag_id else "",
            "enabled": rule.enabled,
        }
        for rule in collection.auto_rules.select_related("category", "tag").all().order_by("id")
    ]

    directory = safe_segment(collection.slug, fallback="collection")
    articles: list[dict] = []
    used_names: dict[str, int] = {}
    image_names: set[str] = set()
    image_names |= extract_media_image_names(collection.description)

    seen_articles: dict[int, BlogArticle] = {}
    for entry in collection.entries.select_related("article").prefetch_related("article__tags").order_by(
        "position", "id"
    ):
        article = entry.article
        if article.id in seen_articles:
            continue
        seen_articles[article.id] = article
        index = len(articles) + 1
        file_name = f"{index:03d}-{safe_segment(article.slug, fallback='article')}.md"
        used_names[file_name] = used_names.get(file_name, 0) + 1
        if used_names[file_name] > 1:
            file_name = f"{index:03d}-{safe_segment(article.slug, fallback='article')}-{used_names[file_name]}.md"
        articles.append(
            {
                "slug": article.slug,
                "title": article.title,
                "summary": article.summary,
                # manifest 是给导入程序读的元数据：保留原始站内路径，不做相对化。
                "cover_image": article.cover_image or "",
                "category": article.category.name if article.category_id else "",
                "tags": [tag.name for tag in article.tags.all()],
                "status": article.status,
                "author_name": article.author_name,
                "remote_images": count_remote_images(article.content),
                "path": f"{ARTICLE_DIR}/{file_name}",
                "markdown": article_markdown(article),
            }
        )
        image_names |= extract_media_image_names(article.content, article.cover_image, article.summary)

    return {
        "directory": directory,
        "collection": {
            "public_id": str(collection.public_id),
            "slug": collection.slug,
            "title": collection.title,
            "description": collection.description,
            "draft_version": collection.draft_version,
            "created_at": collection.created_at.isoformat() if collection.created_at else "",
            "updated_at": collection.updated_at.isoformat() if collection.updated_at else "",
            "nodes": nodes,
            "entries": entries,
            "auto_rules": rules,
            "articles": articles,
            "images": sorted(image_names),
        },
        "images": sorted(image_names),
    }


def _read_blog_image(filename: str) -> bytes | None:
    if not is_blog_image_name(filename):
        return None
    try:
        storage = storages["blog_media"]
        key = f"blog/{filename}"
        if not storage.exists(key):
            return None
        with storage.open(key, "rb") as handle:
            return handle.read()
    except Exception:
        return None


def render_readme(exports: list[dict]) -> str:
    lines = [
        "# 领域笔记导出包",
        "",
        f"- 格式：{ARCHIVE_FORMAT} v{ARCHIVE_VERSION}",
        f"- 导出时间：{timezone.now().isoformat()}",
        f"- 领域数量：{len(exports)}",
        "",
        "正文里的本站图片已放入各领域的 `images/` 目录。由于 `articles/` 与 `images/` 同级，",
        "文章 md 里的链接写成 `../images/<文件名>`，解压后直接用任意 Markdown",
        "阅读器打开即可正常显示配图（不需要搬动文件位置）。",
        "外链图片（http/https）不在本站，未打包，链接保持原样。",
        "",
    ]
    for item in exports:
        data = item["collection"]
        lines.append(f"## {data['title']}（`{item['directory']}/`）")
        if data["description"]:
            lines.append("")
            lines.append(data["description"])
        lines.append("")
        lines.append(f"- 文章 {len(data['articles'])} 篇 · 节点 {len(data['nodes'])} 个 · 图片 {len(data['images'])} 张")
        remote = sum(article.get("remote_images", 0) for article in data["articles"])
        if remote:
            lines.append(f"- 外链图片 {remote} 张（未打包）")
        node_titles = {node["ref"]: node["title"] for node in data["nodes"]}
        lines.append("")
        for article in data["articles"]:
            lines.append(f"- [{article['title']}]({item['directory']}/{article['path']})")
        for entry in data["entries"]:
            label = node_titles.get(entry["node_ref"], "领域根")
            lines.append(f"  - {entry['article_slug']} → {label}")
        lines.append("")
    return "\n".join(lines)


def build_archive_bytes(collections: list[BlogCollection]) -> tuple[bytes, dict]:
    """把若干领域打包成 zip 字节流，返回 (bytes, 统计信息)。"""
    if not collections:
        raise ArchiveError("请先选择要导出的领域", code="empty_export", http_status=400)

    exports = [serialize_collection_export(collection) for collection in collections]
    # 清单只放元数据：正文本体已经在 articles/*.md 里，不重复写入 manifest。
    manifest_collections = []
    for item in exports:
        data = dict(item["collection"])
        data["articles"] = [
            {key: value for key, value in article.items() if key != "markdown"}
            for article in data["articles"]
        ]
        data["directory"] = item["directory"]
        manifest_collections.append(data)
    manifest = {
        "format": ARCHIVE_FORMAT,
        "version": ARCHIVE_VERSION,
        "exported_at": timezone.now().isoformat(),
        "collections": manifest_collections,
    }

    buffer = io.BytesIO()
    written_images: list[str] = []
    missing_images: list[str] = []
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr(README_NAME, render_readme(exports))
        for item in exports:
            base = item["directory"]
            for article in item["collection"]["articles"]:
                archive.writestr(f"{base}/{article['path']}", article["markdown"])
            for name in item["images"]:
                data = _read_blog_image(name)
                if data is None:
                    missing_images.append(name)
                    continue
                archive.writestr(f"{base}/{IMAGE_DIR}/{name}", data)
                written_images.append(name)

    stats = {
        "collections": len(exports),
        "articles": sum(len(item["collection"]["articles"]) for item in exports),
        "images": len(written_images),
        "missing_images": missing_images,
        "nodes": sum(len(item["collection"]["nodes"]) for item in exports),
    }
    return buffer.getvalue(), stats


def export_filename(collections: list[BlogCollection]) -> str:
    """ASCII-only 文件名：Content-Disposition 走 RFC 5987 编码会影响部分下载器。"""
    stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    if len(collections) == 1:
        ascii_slug = slugify(collections[0].slug) or "export"
        return f"blog-collection-{ascii_slug[:60]}-{stamp}.zip"
    return f"blog-collections-{len(collections)}-{stamp}.zip"


# --------------------------------------------------------------------------- 导入


def _safe_member_paths(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """过滤目录穿越与绝对路径，返回 (包内相对路径 -> ZipInfo)。"""
    members: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ":" in name.split("/")[0]:
            continue
        parts = []
        for part in name.split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                parts = []
                continue
            parts.append(part)
        if not parts:
            continue
        if info.is_dir():
            continue
        members["/".join(parts)] = info
    return members


def parse_manifest(raw: bytes) -> dict:
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ArchiveError("清单文件过大", code="archive_too_large", http_status=413)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ArchiveError("manifest.json 无法解析", code="bad_manifest") from None
    if not isinstance(payload, dict) or payload.get("format") != ARCHIVE_FORMAT:
        raise ArchiveError("不是有效的领域导出包", code="bad_manifest")
    if not isinstance(payload.get("collections"), list) or not payload["collections"]:
        raise ArchiveError("导出包里没有任何领域", code="empty_manifest")
    return payload


def read_archive(upload) -> tuple[dict, dict[str, bytes]]:
    """校验并读入上传的 zip，返回 (manifest, {包内路径: 字节})。"""
    raw = upload.read()
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise ArchiveError("压缩包不能超过 200 MiB", code="archive_too_large", http_status=413)
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise ArchiveError("文件不是有效的 zip 压缩包", code="bad_archive") from None

    with archive:
        members = _safe_member_paths(archive)
        if len(members) > MAX_ARCHIVE_FILES:
            raise ArchiveError(
                f"压缩包内文件过多（最多 {MAX_ARCHIVE_FILES} 个）", code="archive_too_large", http_status=413
            )
        total = sum(info.file_size for info in members.values())
        if total > MAX_ARCHIVE_BYTES * MAX_UNCOMPRESSED_RATIO // 10:
            raise ArchiveError("压缩包解压后体积异常", code="archive_too_large", http_status=413)
        if MANIFEST_NAME not in members:
            raise ArchiveError("压缩包缺少 manifest.json", code="bad_manifest")
        files: dict[str, bytes] = {}
        for path, info in members.items():
            data = archive.read(info)
            if len(data) > MAX_IMAGE_BYTES and path.startswith(IMAGE_DIR):
                raise ArchiveError(f"{path} 超过单张图片大小上限", code="image_too_large", http_status=413)
            files[path] = data
    return parse_manifest(files.pop(MANIFEST_NAME)), files


def _rewrite_imported_text(text: str, mapping: dict[str, str]) -> str:
    """把包内相对图片路径还原成站内 /media/blog/ 链接。"""
    if not text or not mapping:
        return text or ""

    def replace(match: re.Match) -> str:
        name = match.group(1)
        return f"/media/blog/{mapping.get(name, name)}"

    return ARCHIVE_IMAGE_RE.sub(replace, text)


def _store_image(name: str, data: bytes) -> str | None:
    """写入 blog_media；文件名合法则保留原名（重复导入不会堆积副本）。"""
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    target = name if is_blog_image_name(name) else f"{uuid.uuid4().hex}.{suffix or 'png'}"
    try:
        validate_blog_image(io.BytesIO(data), target)
    except ValueError:
        return None
    try:
        storage = storages["blog_media"]
        key = f"blog/{target}"
        if not storage.exists(key):
            storage.save(key, ContentFile(data))
    except Exception:
        return None
    return target


def _unique_taxonomy_slug(model, name: str) -> str:
    """分类/标签只有全局唯一的 name 与 slug，创建时需自行保证 slug 不撞车。"""
    base = (slugify(name, allow_unicode=True) or uuid.uuid4().hex[:10])[:80]
    if not model.objects.filter(slug=base).exists():
        return base
    return f"{base[:70]}-{uuid.uuid4().hex[:6]}"


def _get_or_create_category(name: str):
    category = ArticleCategory.objects.filter(name=name[:60]).first()
    if category:
        return category
    return ArticleCategory.objects.create(name=name[:60], slug=_unique_taxonomy_slug(ArticleCategory, name))


def _get_or_create_tag(name: str):
    tag = ArticleTag.objects.filter(name=name[:60]).first()
    if tag:
        return tag
    return ArticleTag.objects.create(name=name[:60], slug=_unique_taxonomy_slug(ArticleTag, name))


def _unique_slug(model, candidate: str, workspace_key: str, *, owner=None) -> str:
    base = slugify(candidate, allow_unicode=True) or "item"
    queryset = model.objects.filter(slug=base, workspace_key=workspace_key)
    if owner is not None and hasattr(model, "owner"):
        queryset = queryset.filter(owner=owner)
    if not queryset.exists():
        return base
    for index in range(2, 100):
        attempt = f"{base}-{index}"
        probe = model.objects.filter(slug=attempt, workspace_key=workspace_key)
        if owner is not None and hasattr(model, "owner"):
            probe = probe.filter(owner=owner)
        if not probe.exists():
            return attempt
    return f"{base}-{uuid.uuid4().hex[:8]}"


def plan_import(payload: dict, files: dict[str, bytes], *, workspace_key: str, owner=None) -> dict:
    """只读预演：统计将要创建/复用/跳过的对象，不写任何数据。"""
    report: dict = {
        "collections": [],
        "totals": {"collections": 0, "articles": 0, "images": 0, "nodes": 0, "entries": 0, "skipped_articles": 0},
        "warnings": [],
    }
    for item in payload["collections"]:
        directory = safe_segment(str(item.get("directory") or item.get("slug") or "collection"))
        images = [name for name in item.get("images", []) if f"{directory}/{IMAGE_DIR}/{name}" in files]
        missing = [name for name in item.get("images", []) if f"{directory}/{IMAGE_DIR}/{name}" not in files]
        articles = item.get("articles", [])
        existing = BlogArticle.objects.filter(
            workspace_key=workspace_key, slug__in=[a.get("slug") for a in articles if a.get("slug")]
        ).values_list("slug", flat=True)
        existing_slugs = set(existing)
        collection_exists = False
        slug = str(item.get("slug") or "")
        if slug:
            probe = BlogCollection.objects.filter(slug=slug, workspace_key=workspace_key)
            if owner is not None:
                probe = probe.filter(owner=owner)
            collection_exists = probe.exists()
        report["collections"].append(
            {
                "directory": directory,
                "title": item.get("title", ""),
                "slug": slug,
                "collection_exists": collection_exists,
                "nodes": len(item.get("nodes", [])),
                "entries": len(item.get("entries", [])),
                "articles": len(articles),
                "new_articles": len([a for a in articles if a.get("slug") not in existing_slugs]),
                "skipped_articles": len([a for a in articles if a.get("slug") in existing_slugs]),
                "images": len(images),
                "missing_images": missing,
            }
        )
        report["totals"]["collections"] += 1
        report["totals"]["articles"] += len(articles)
        report["totals"]["images"] += len(images)
        report["totals"]["nodes"] += len(item.get("nodes", []))
        report["totals"]["entries"] += len(item.get("entries", []))
        report["totals"]["skipped_articles"] += len([a for a in articles if a.get("slug") in existing_slugs])
        if missing:
            report["warnings"].append(f"{item.get('title', directory)}：{len(missing)} 张图片在包里缺失")
    return report


def apply_import(
    payload: dict,
    files: dict[str, bytes],
    *,
    owner,
    workspace_key: str,
    conflict: str = CONFLICT_SKIP,
) -> dict:
    """按 manifest 重建领域；整体在一个事务里，失败即全部回滚。"""
    if conflict not in CONFLICT_CHOICES:
        raise ArchiveError("冲突策略无效", code="bad_conflict")

    from django.db import transaction

    result = {"collections": [], "totals": {"collections": 0, "articles": 0, "images": 0, "nodes": 0, "entries": 0}}

    with transaction.atomic():
        for item in payload["collections"]:
            directory = safe_segment(str(item.get("directory") or item.get("slug") or "collection"))
            mapping: dict[str, str] = {}
            stored_images = 0
            for name in item.get("images", []):
                data = files.get(f"{directory}/{IMAGE_DIR}/{name}")
                if not data:
                    continue
                target = _store_image(name, data)
                if target:
                    mapping[name] = target
                    stored_images += 1

            slug = str(item.get("slug") or "") or "collection"
            title = str(item.get("title") or slug)[:120]
            description = str(item.get("description") or "")[:500]
            existing_collection = BlogCollection.objects.filter(
                slug=slug, workspace_key=workspace_key, owner=owner
            ).first()
            if existing_collection:
                if conflict == CONFLICT_SKIP:
                    result["collections"].append(
                        {"title": title, "slug": slug, "status": "skipped", "articles": 0, "images": stored_images}
                    )
                    result["totals"]["images"] += stored_images
                    continue
                if conflict == CONFLICT_RENAME:
                    slug = _unique_slug(BlogCollection, slug, workspace_key, owner=owner)
                    existing_collection = None
                else:
                    existing_collection.title = title
                    existing_collection.description = description
                    existing_collection.save(update_fields=["title", "description", "updated_at"])
            if existing_collection is None:
                slug = _unique_slug(BlogCollection, slug, workspace_key, owner=owner)
                existing_collection = BlogCollection.objects.create(
                    owner=owner,
                    workspace_key=workspace_key,
                    title=title,
                    slug=slug,
                    description=description,
                )

            node_by_ref: dict[object, BlogCollectionNode] = {}
            pending_children: list[tuple[BlogCollectionNode, object]] = []
            for raw_node in item.get("nodes", []):
                node = BlogCollectionNode.objects.create(
                    collection=existing_collection,
                    title=str(raw_node.get("title") or "节点")[:120],
                    description=str(raw_node.get("description") or "")[:500],
                    position=int(raw_node.get("position") or 0),
                )
                ref = raw_node.get("ref")
                node_by_ref[ref] = node
                if raw_node.get("parent_ref"):
                    pending_children.append((node, raw_node.get("parent_ref")))
            for node, parent_ref in pending_children:
                parent = node_by_ref.get(parent_ref)
                if parent is not None:
                    node.parent = parent
                    node.save(update_fields=["parent"])

            article_by_slug: dict[str, BlogArticle] = {}
            created_articles = 0
            for raw_article in item.get("articles", []):
                article_slug = str(raw_article.get("slug") or "")
                path = str(raw_article.get("path") or "")
                body = ""
                if path:
                    body = _strip_front_matter((files.get(f"{directory}/{path}") or b"").decode("utf-8", "ignore"))
                article = None
                if article_slug:
                    article = BlogArticle.objects.filter(slug=article_slug, workspace_key=workspace_key).first()
                if article is not None:
                    if conflict == CONFLICT_SKIP:
                        article_by_slug[article_slug] = article
                        continue
                    if conflict == CONFLICT_RENAME:
                        article = None
                if article is None:
                    base_slug = article_slug or slugify(str(raw_article.get("title") or "article"), allow_unicode=True)
                    final_slug = _unique_slug(BlogArticle, base_slug, workspace_key)
                    article = BlogArticle.objects.create(
                        title=str(raw_article.get("title") or base_slug)[:180],
                        workspace_key=workspace_key,
                        slug=final_slug,
                        author_name=str(raw_article.get("author_name") or "")[:80],
                        summary=str(raw_article.get("summary") or ""),
                        cover_image=_rewrite_imported_text(str(raw_article.get("cover_image") or ""), mapping),
                        content=_rewrite_imported_text(body, mapping),
                        status=BlogArticle.Status.DRAFT,
                    )
                    created_articles += 1
                else:
                    article.title = str(raw_article.get("title") or article.title)[:180]
                    article.summary = str(raw_article.get("summary") or "")
                    article.content = _rewrite_imported_text(body or article.content, mapping)
                    cover = _rewrite_imported_text(str(raw_article.get("cover_image") or ""), mapping)
                    if cover:
                        article.cover_image = cover
                    article.save(update_fields=["title", "summary", "content", "cover_image", "updated_at"])
                category_name = str(raw_article.get("category") or "").strip()
                if category_name:
                    article.category = _get_or_create_category(category_name)
                    article.save(update_fields=["category"])
                tag_names = [str(tag).strip() for tag in raw_article.get("tags", []) if str(tag).strip()]
                if tag_names:
                    article.tags.set([_get_or_create_tag(tag_name) for tag_name in tag_names[:12]])
                article_by_slug[article_slug or final_slug] = article
                article_by_slug.setdefault(article.slug, article)

            entries_created = 0
            for raw_entry in item.get("entries", []):
                article = article_by_slug.get(str(raw_entry.get("article_slug") or ""))
                if article is None:
                    continue
                node = node_by_ref.get(raw_entry.get("node_ref"))
                if existing_collection.entries.filter(article=article).exists():
                    continue
                BlogCollectionEntry.objects.create(
                    collection=existing_collection,
                    node=node,
                    article=article,
                    position=int(raw_entry.get("position") or 0),
                )
                entries_created += 1

            rules_created = 0
            for raw_rule in item.get("auto_rules", []):
                category_name = str(raw_rule.get("category") or "").strip()
                if not category_name:
                    continue
                category = _get_or_create_category(category_name)
                tag = None
                tag_name = str(raw_rule.get("tag") or "").strip()
                if tag_name:
                    tag = _get_or_create_tag(tag_name)
                BlogCollectionAutoRule.objects.get_or_create(
                    collection=existing_collection,
                    category=category,
                    tag=tag,
                    node=node_by_ref.get(raw_rule.get("node_ref")),
                    defaults={"enabled": bool(raw_rule.get("enabled", True))},
                )
                rules_created += 1

            result["collections"].append(
                {
                    "title": title,
                    "slug": existing_collection.slug,
                    "public_id": str(existing_collection.public_id),
                    "status": "created",
                    "articles": created_articles,
                    "images": stored_images,
                    "nodes": len(node_by_ref),
                    "entries": entries_created,
                    "rules": rules_created,
                }
            )
            result["totals"]["collections"] += 1
            result["totals"]["articles"] += created_articles
            result["totals"]["images"] += stored_images
            result["totals"]["nodes"] += len(node_by_ref)
            result["totals"]["entries"] += entries_created
    return result


def _strip_front_matter(text: str) -> str:
    """去掉 `---` 包裹的 front-matter，只留正文。"""
    if not text.startswith("---"):
        return text
    lines = text.split("\n")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1 :]).lstrip("\n")
    return text
