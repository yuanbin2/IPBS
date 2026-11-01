"""领域归档导出/导入（B-067）：包结构、图片打包、链接改写与导入重建。"""

import io
import json
import os
import tempfile
import uuid
import zipfile

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from ..models import BlogArticle, BlogCollection, BlogCollectionEntry, BlogCollectionNode
from ..services.collection_archive import (
    ARCHIVE_FORMAT,
    ARTICLE_IMAGE_PREFIX,
    CONFLICT_RENAME,
    CONFLICT_SKIP,
    _rewrite_imported_text,
    apply_import,
    build_archive_bytes,
    parse_manifest,
    plan_import,
    read_archive,
    rewrite_to_archive,
)
from .support import OperatorApiTestCase

COLLECTIONS_BASE = "/api/agent/blog/collections/"
EXPORT_BASE = "/api/agent/blog/collections/export/"
IMPORT_URL = "/api/agent/blog/collections/import/"


def png_bytes(color=(10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buffer, format="PNG")
    return buffer.getvalue()


class ArchiveTestCase(OperatorApiTestCase):
    def setUp(self):
        super().setUp()
        self.media_dir = tempfile.mkdtemp(prefix="archive-media-")
        self.media_settings = {
            **settings.STORAGES,
            "blog_media": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": self.media_dir, "base_url": "/media/"},
            },
        }
        self.storage_override = override_settings(STORAGES=self.media_settings)
        self.storage_override.enable()
        # 早期迁移会播种示例文章/领域，断言一律用相对增量而不是绝对数量。
        self.baseline_articles = BlogArticle.objects.count()
        self.baseline_collections = BlogCollection.objects.count()
        self.seeded_collection_slugs = list(BlogCollection.objects.values_list("slug", flat=True))
        self.seeded_article_slugs = list(BlogArticle.objects.values_list("slug", flat=True))

    def tearDown(self):
        self.storage_override.disable()
        super().tearDown()

    def store_image(self) -> tuple[str, str]:
        """写入一张真实 PNG，返回 (文件名, 站内链接)。"""
        name = f"{uuid.uuid4().hex}.png"
        storage = storages["blog_media"]
        storage.save(f"blog/{name}", ContentFile(png_bytes()))
        return name, f"/media/blog/{name}"

    def create_collection(self, title="归档领域"):
        response = self.client.post(
            COLLECTIONS_BASE, json.dumps({"title": title}), content_type="application/json", HTTP_HOST="localhost"
        )
        self.assertEqual(response.status_code, 201, response.content)
        public_id = response.json()["public_id"]
        return BlogCollection.objects.get(public_id=public_id)

    def add_article(self, collection, node, title, content):
        article = BlogArticle.objects.create(
            title=title,
            slug=f"slug-{uuid.uuid4().hex[:10]}",
            workspace_key="default",
            content=content,
            status=BlogArticle.Status.PUBLISHED,
            author_name="tester",
        )
        BlogCollectionEntry.objects.create(collection=collection, node=node, article=article, position=0)
        return article

    def upload(self, payload: bytes, name="bundle.zip"):
        return SimpleUploadedFile(name, payload, content_type="application/zip")


class ExportTests(ArchiveTestCase):
    def test_archive_contains_manifest_articles_and_images(self):
        collection = self.create_collection()
        node = collection.nodes.create(title="第一章", position=0)
        child = collection.nodes.create(title="小节", parent=node, position=0)
        name, url = self.store_image()
        self.add_article(collection, child, "带图文章", f"开头\n\n![配图]({url})\n\n结尾")

        payload, stats = build_archive_bytes([collection])
        self.assertEqual(stats["articles"], 1)
        self.assertEqual(stats["images"], 1)
        self.assertEqual(stats["missing_images"], [])

        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn("README.md", names)
            directory = collection.slug
            self.assertIn(f"{directory}/images/{name}", names)
            article_paths = [n for n in names if n.startswith(f"{directory}/articles/") and n.endswith(".md")]
            self.assertEqual(len(article_paths), 1)
            body = archive.read(article_paths[0]).decode("utf-8")
            # articles/ 与 images/ 同级，链接必须回退一级，否则解压后图片打不开。
            self.assertIn(f"](../images/{name})", body)
            self.assertNotIn("/media/blog/", body)
            self.assertEqual(archive.read(f"{directory}/images/{name}"), png_bytes())
            manifest = parse_manifest(archive.read("manifest.json"))
        self.assertEqual(manifest["format"], ARCHIVE_FORMAT)
        self.assertEqual(len(manifest["collections"]), 1)
        exported = manifest["collections"][0]
        self.assertEqual(len(exported["nodes"]), 2)
        self.assertEqual(exported["nodes"][1]["parent_ref"], exported["nodes"][0]["ref"])
        self.assertEqual(exported["articles"][0]["title"], "带图文章")

    def test_manifest_does_not_duplicate_article_bodies(self):
        collection = self.create_collection()
        node = collection.nodes.create(title="章", position=0)
        self.add_article(collection, node, "正文", "x" * 500)
        payload, _ = build_archive_bytes([collection])
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            raw = archive.read("manifest.json").decode("utf-8")
        self.assertNotIn("x" * 100, raw)

    def test_missing_image_is_reported_not_failed(self):
        collection = self.create_collection()
        node = collection.nodes.create(title="章", position=0)
        missing = f"{uuid.uuid4().hex}.png"
        self.add_article(collection, node, "缺图文章", f"![图](/media/blog/{missing})")
        payload, stats = build_archive_bytes([collection])
        self.assertEqual(stats["images"], 0)
        self.assertEqual(stats["missing_images"], [missing])
        self.assertTrue(payload)

    def test_single_collection_export_endpoint(self):
        collection = self.create_collection()
        node = collection.nodes.create(title="章", position=0)
        name, url = self.store_image()
        self.add_article(collection, node, "接口导出", f"![图]({url})")
        response = self.client.get(f"{COLLECTIONS_BASE}{collection.public_id}/export/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn(".zip", response["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertIn(f"{collection.slug}/images/{name}", set(archive.namelist()))

    def test_bulk_export_packs_every_selected_collection(self):
        first = self.create_collection("领域甲")
        second = self.create_collection("领域乙")
        for collection in (first, second):
            node = collection.nodes.create(title="章", position=0)
            self.add_article(collection, node, f"{collection.title}文章", "正文")
        response = self.client.get(
            EXPORT_BASE, {"ids": f"{first.public_id},{second.public_id}"}, HTTP_HOST="localhost"
        )
        self.assertEqual(response.status_code, 200, response.content)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            manifest = parse_manifest(archive.read("manifest.json"))
        self.assertEqual(len(manifest["collections"]), 2)
        self.assertEqual({item["directory"] for item in manifest["collections"]}, {first.slug, second.slug})

    def test_bulk_export_requires_ids_and_login(self):
        self.assertEqual(self.client.get(EXPORT_BASE, HTTP_HOST="localhost").status_code, 400)


class ImportTests(ArchiveTestCase):
    def build_bundle(self, *, image_url: str | None = None, image_name: str | None = None) -> bytes:
        collection = self.create_collection()
        node = collection.nodes.create(title="导入章", position=0)
        child = collection.nodes.create(title="导入小节", parent=node, position=0)
        content = f"![配图]({image_url})" if image_url else "纯文本"
        article = self.add_article(collection, child, "导入文章", content)
        payload, _ = build_archive_bytes([collection])
        # 清掉原领域，模拟迁移到空库
        article.delete()
        collection.delete()
        self.bundle_image_name = image_name
        return payload

    def test_preview_reports_counts_without_writing(self):
        name, url = self.store_image()
        payload = self.build_bundle(image_url=url, image_name=name)
        response = self.client.post(
            IMPORT_URL, {"file": self.upload(payload), "mode": "preview"}, HTTP_HOST="localhost"
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["mode"], "preview")
        self.assertEqual(body["totals"]["collections"], 1)
        self.assertEqual(body["totals"]["articles"], 1)
        self.assertEqual(body["totals"]["images"], 1)
        self.assertEqual(body["totals"]["nodes"], 2)
        self.assertEqual(BlogCollection.objects.count(), self.baseline_collections)
        self.assertEqual(BlogArticle.objects.count(), self.baseline_articles)

    def test_apply_rebuilds_tree_articles_and_images(self):
        name, url = self.store_image()
        payload = self.build_bundle(image_url=url, image_name=name)
        response = self.client.post(
            IMPORT_URL, {"file": self.upload(payload), "mode": "apply"}, HTTP_HOST="localhost"
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["totals"]["collections"], 1)
        self.assertEqual(body["totals"]["articles"], 1)
        self.assertEqual(body["totals"]["images"], 1)
        self.assertEqual(body["totals"]["entries"], 1)

        collection = BlogCollection.objects.exclude(slug__in=self.seeded_collection_slugs).get(title="归档领域")
        self.assertEqual(collection.nodes.count(), 2)
        child = collection.nodes.get(title="导入小节")
        self.assertIsNotNone(child.parent_id)
        self.assertEqual(child.parent.title, "导入章")
        article = collection.entries.get().article
        self.assertIn(f"/media/blog/{name}", article.content)
        # 包内的 ../images/ 必须被还原干净，不能留下 ../ 前缀或相对路径残影。
        self.assertNotIn("../images/", article.content)
        self.assertNotIn("../media/", article.content)
        self.assertTrue(storages["blog_media"].exists(f"blog/{name}"))
        self.assertEqual(BlogCollectionEntry.objects.filter(collection=collection, article=article).count(), 1)

    def test_conflict_skip_keeps_existing_article(self):
        name, url = self.store_image()
        payload = self.build_bundle(image_url=url, image_name=name)
        response = self.client.post(IMPORT_URL, {"file": self.upload(payload), "mode": "preview"}, HTTP_HOST="localhost")
        manifest_slug = None
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            manifest_slug = json.loads(archive.read("manifest.json"))["collections"][0]["articles"][0]["slug"]
        existing = BlogArticle.objects.create(
            title="已有", slug=manifest_slug, workspace_key="default", content="原始内容", status=BlogArticle.Status.DRAFT
        )
        response = self.client.post(
            IMPORT_URL,
            {"file": self.upload(payload), "mode": "apply", "conflict": CONFLICT_SKIP},
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 201, response.content)
        existing.refresh_from_db()
        self.assertEqual(existing.content, "原始内容")
        self.assertEqual(BlogArticle.objects.count(), self.baseline_articles + 1)

    def test_conflict_rename_creates_new_slug(self):
        name, url = self.store_image()
        payload = self.build_bundle(image_url=url, image_name=name)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            manifest_slug = json.loads(archive.read("manifest.json"))["collections"][0]["articles"][0]["slug"]
        BlogArticle.objects.create(
            title="已有", slug=manifest_slug, workspace_key="default", content="原始内容", status=BlogArticle.Status.DRAFT
        )
        response = self.client.post(
            IMPORT_URL,
            {"file": self.upload(payload), "mode": "apply", "conflict": CONFLICT_RENAME},
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(BlogArticle.objects.count(), self.baseline_articles + 2)
        self.assertTrue(BlogArticle.objects.filter(slug__startswith=f"{manifest_slug}-").exists())

    def test_rejects_non_zip_payload(self):
        response = self.client.post(
            IMPORT_URL, {"file": self.upload(b"not a zip", "note.txt")}, HTTP_HOST="localhost"
        )
        self.assertEqual(response.status_code, 400)

    def test_rejects_archive_without_manifest(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("articles/a.md", "hello")
        response = self.client.post(IMPORT_URL, {"file": self.upload(buffer.getvalue())}, HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 400)

    def test_zip_slip_paths_are_flattened(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"format": ARCHIVE_FORMAT, "collections": []}))
            archive.writestr("../../../evil.txt", "pwned")
        upload = self.upload(buffer.getvalue())
        try:
            read_archive(upload)
        except Exception:
            pass
        for path in ("evil.txt", "../../../evil.txt"):
            self.assertFalse(os.path.exists(os.path.join(self.media_dir, "..", path)))

    def test_absolute_media_url_is_rewritten_to_relative(self):
        """正文里由编辑器写入的绝对地址也要归一成包内相对路径（不能吃掉斜杠）。"""
        collection = self.create_collection()
        node = collection.nodes.create(title="章", position=0)
        name, _ = self.store_image()
        absolute = f"http://127.0.0.1:5174/media/blog/{name}"
        self.add_article(collection, node, "绝对地址", f"![图]({absolute})")
        payload, stats = build_archive_bytes([collection])
        self.assertEqual(stats["images"], 1)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            path = [n for n in archive.namelist() if "/articles/" in n and n.endswith(".md")][0]
            body = archive.read(path).decode("utf-8")
        self.assertIn(f"](../images/{name})", body)
        self.assertNotIn("5174images/", body)
        self.assertNotIn("127.0.0.1", body)

    def test_rewrite_roundtrip(self):
        # articles/ 与 images/ 同级，前缀必须回退一级，否则解压后图片打不开。
        self.assertEqual(ARTICLE_IMAGE_PREFIX, "../images/")
        name = f"{uuid.uuid4().hex}.jpg"
        text = f"![a](/media/blog/{name})"
        archived = rewrite_to_archive(text)
        self.assertEqual(archived, f"![a](../images/{name})")
        # 导入侧必须同时认得 ../images/、images/ 与裸 /media/blog/ 三种写法。
        for candidate in (archived, f"![a](images/{name})", text):
            self.assertEqual(_rewrite_imported_text(candidate, {name: name}), text)
        self.assertEqual(rewrite_to_archive("没有图片"), "没有图片")


class ImportPlanTests(ArchiveTestCase):
    def test_plan_flags_missing_images(self):
        collection = self.create_collection()
        node = collection.nodes.create(title="章", position=0)
        missing = f"{uuid.uuid4().hex}.png"
        self.add_article(collection, node, "缺图", f"![图](/media/blog/{missing})")
        payload, _ = build_archive_bytes([collection])
        manifest, files = read_archive(self.upload(payload))
        report = plan_import(manifest, files, workspace_key="default", owner=self.test_user)
        self.assertEqual(report["totals"]["images"], 0)
        self.assertEqual(report["collections"][0]["missing_images"], [missing])
        self.assertTrue(report["warnings"])

    def test_apply_import_rejects_unknown_conflict(self):
        collection = self.create_collection()
        payload, _ = build_archive_bytes([collection])
        manifest, files = read_archive(self.upload(payload))
        with self.assertRaises(Exception):
            apply_import(manifest, files, owner=self.test_user, workspace_key="default", conflict="explode")
