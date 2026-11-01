"""Private notes stay tied to a real user and workspace and never publish."""

import json
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from ..models import BlogArticle, PrivateNote, PrivateNoteImage, UserProfile
from ..views.blog_note_images import cleanup_orphan_private_images
from .support import TEST_MEDIA_ROOT, OperatorApiTestCase


class PrivateNoteApiTests(OperatorApiTestCase):
    notes_url = "/api/agent/blog/notes/"

    def test_create_search_update_conflict_delete_and_restore(self):
        article = BlogArticle.objects.create(
            title="Public source",
            slug="note-source",
            author_name="other",
            content="Published",
            status=BlogArticle.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        created = self.client.post(
            self.notes_url,
            {
                "title": "My idea",
                "content": "A private observation",
                "quote": "Published",
                "source_article": article.id,
            },
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(created.status_code, 201)
        note_id = created.json()["id"]
        self.assertEqual(created.json()["source_article_slug"], article.slug)
        self.assertEqual(PrivateNote.objects.get(pk=note_id).owner, self.test_user)
        found = self.client.get(f"{self.notes_url}?q=observation", HTTP_HOST="localhost")
        self.assertEqual(found.json()["total"], 1)

        updated = self.client.put(
            f"{self.notes_url}{note_id}/",
            {"title": "Revised idea", "content": "Safe text", "version": 1},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["version"], 2)
        conflict = self.client.put(
            f"{self.notes_url}{note_id}/",
            {"title": "Stale", "version": 1},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(PrivateNote.objects.get(pk=note_id).title, "Revised idea")

        deleted = self.client.delete(f"{self.notes_url}{note_id}/", HTTP_HOST="localhost")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(self.notes_url, HTTP_HOST="localhost").json()["total"], 0)
        self.assertEqual(self.client.get(f"{self.notes_url}{note_id}/", HTTP_HOST="localhost").status_code, 404)
        self.assertEqual(self.client.get(f"{self.notes_url}?deleted=1", HTTP_HOST="localhost").json()["total"], 1)
        restored = self.client.post(f"{self.notes_url}{note_id}/restore/", HTTP_HOST="localhost")
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()["version"], 4)
        self.assertEqual(self.client.get(self.notes_url, HTTP_HOST="localhost").json()["total"], 1)
        self.assertFalse(article.knowledge_document_id)

    def test_another_account_and_workspace_cannot_read_or_write_note(self):
        created = self.client.post(
            self.notes_url,
            {"title": "Secret", "content": "Only mine"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        note_id = created.json()["id"]
        self.authenticate_test_user(UserProfile.Role.ADMIN, workspace_key="default")
        self.assertEqual(self.client.get(self.notes_url, HTTP_HOST="localhost").json()["total"], 0)
        self.assertEqual(self.client.get(f"{self.notes_url}{note_id}/", HTTP_HOST="localhost").status_code, 404)
        self.assertEqual(
            self.client.put(
                f"{self.notes_url}{note_id}/",
                {"title": "Nope", "version": 1},
                content_type="application/json",
                HTTP_HOST="localhost",
            ).status_code,
            404,
        )
        self.assertEqual(self.client.delete(f"{self.notes_url}{note_id}/", HTTP_HOST="localhost").status_code, 404)
        self.authenticate_test_user(UserProfile.Role.OPERATOR, workspace_key="other")
        self.assertEqual(self.client.get(f"{self.notes_url}{note_id}/", HTTP_HOST="localhost").status_code, 404)

    def test_dev_role_header_and_cookie_cannot_access_notes(self):
        self.client.defaults.pop("HTTP_AUTHORIZATION")
        self.client.defaults["HTTP_X_ROLE"] = "admin"
        self.assertEqual(self.client.get(self.notes_url, HTTP_HOST="localhost").status_code, 401)
        self.assertEqual(
            self.client.post(
                self.notes_url,
                {"title": "Unowned"},
                content_type="application/json",
                HTTP_HOST="localhost",
            ).status_code,
            401,
        )

    def test_foreign_or_private_source_article_is_rejected(self):
        foreign = BlogArticle.objects.create(
            title="Other workspace",
            slug="foreign-note-source",
            workspace_key="other",
            content="Hidden",
            status=BlogArticle.Status.PUBLISHED,
        )
        private = BlogArticle.objects.create(
            title="Someone's draft",
            slug="private-note-source",
            author_name="another-user",
            content="Hidden",
        )
        for article in (foreign, private):
            response = self.client.post(
                self.notes_url,
                {"title": "No", "source_article": article.id},
                content_type="application/json",
                HTTP_HOST="localhost",
            )
            self.assertEqual(response.status_code, 400)
        self.assertEqual(PrivateNote.objects.count(), 0)

    def test_article_annotations_keep_anchor_and_filter_to_owner_article(self):
        article = BlogArticle.objects.create(
            title="Reading source",
            slug="reading-source",
            author_name=self.test_user.username,
            content="Repeat phrase. Repeat phrase.",
            status=BlogArticle.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        other_article = BlogArticle.objects.create(
            title="Another source",
            slug="another-source",
            author_name=self.test_user.username,
            content="Another phrase.",
            status=BlogArticle.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        highlighted = self.client.post(
            self.notes_url,
            {
                "title": "Highlight",
                "quote": "Repeat phrase",
                "anchor_offset": 15,
                "source_article": article.id,
            },
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(highlighted.status_code, 201)
        self.assertEqual(highlighted.json()["anchor_offset"], 15)
        self.client.post(
            self.notes_url,
            {"title": "Other", "source_article": other_article.id},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        listed = self.client.get(f"{self.notes_url}?source_article={article.id}", HTTP_HOST="localhost")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total"], 1)
        self.assertEqual(listed.json()["items"][0]["id"], highlighted.json()["id"])
        self.assertEqual(
            self.client.get(f"{self.notes_url}?source_article=bad", HTTP_HOST="localhost").status_code, 400
        )
        invalid = self.client.post(
            self.notes_url,
            {"title": "Bad", "source_article": article.id, "anchor_offset": -1},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(invalid.status_code, 400)
        self.authenticate_test_user(UserProfile.Role.ADMIN, workspace_key="default")
        self.assertEqual(
            self.client.get(f"{self.notes_url}?source_article={article.id}", HTTP_HOST="localhost").json()["total"],
            0,
        )


class PrivateNoteWebClipSourceTests(OperatorApiTestCase):
    """B-043：外部网页剪藏来源字段、隔离与互斥语义。"""

    notes_url = "/api/agent/blog/notes/"

    def _create(self, **fields):
        return self.client.post(
            self.notes_url,
            json.dumps({"title": "网页剪藏", "content": "正文", **fields}),
            content_type="application/json",
            HTTP_HOST="localhost",
        )

    def test_web_clip_source_is_stored_without_server_fetch(self):
        response = self._create(
            source_url="https://example.org/post?utm_source=share&utm_medium=wechat&x=1",
            source_title="某篇示例文章",
        )
        self.assertEqual(response.status_code, 201)
        note = PrivateNote.objects.get(pk=response.json()["id"])
        # 跟踪参数被去掉，其余查询参数保留
        self.assertEqual(note.source_url, "https://example.org/post?x=1")
        self.assertEqual(note.source_title, "某篇示例文章")
        self.assertIsNone(note.source_article)
        self.assertIsNone(note.captured_at)

    def test_source_url_rejects_credentials_bad_scheme_and_oversize(self):
        for raw in [
            "https://user:pass@example.org/post",
            "javascript:alert(1)",
            "ftp://example.org/post",
            "x" * 2049,
            "not a url",
        ]:
            with self.subTest(raw=raw[:40]):
                response = self._create(source_url=raw)
                self.assertEqual(response.status_code, 400)

    def test_source_url_and_source_article_are_mutually_exclusive(self):
        article = BlogArticle.objects.create(
            title="Public",
            slug="webclip-mutex",
            author_name="other",
            content="body",
            status=BlogArticle.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        response = self._create(source_article=article.pk, source_url="https://example.org/x")
        self.assertEqual(response.status_code, 400)

    def test_search_matches_external_source_title(self):
        self._create(source_url="https://example.org/a", source_title="可搜索的来源标题")
        found = self.client.get(self.notes_url + "?q=可搜索的来源标题", HTTP_HOST="localhost")
        self.assertEqual(found.status_code, 200)
        self.assertEqual(len(found.json()["items"]), 1)

    def test_legacy_notes_without_source_fields_still_serialize(self):
        legacy = PrivateNote.objects.create(
            owner=self.test_user,
            workspace_key="default",
            title="旧笔记",
            content="旧内容",
        )
        detail = self.client.get(f"{self.notes_url}{legacy.pk}/", HTTP_HOST="localhost")
        self.assertEqual(detail.status_code, 200)
        payload = detail.json()
        self.assertEqual(payload["source_url"], "")
        self.assertEqual(payload["source_title"], "")
        self.assertIsNone(payload["captured_at"])
        self.assertIsNone(payload["source_article"])

    def test_cross_user_and_workspace_cannot_read_web_clip_note(self):
        created = self._create(source_url="https://example.org/private", source_title="隐私网页")
        note_id = created.json()["id"]
        self.authenticate_test_user("operator", workspace_key="other-space")
        detail = self.client.get(f"{self.notes_url}{note_id}/", HTTP_HOST="localhost")
        self.assertEqual(detail.status_code, 404)
        deleted = self.client.delete(
            f"{self.notes_url}{note_id}/",
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(deleted.status_code, 404)
        self.assertTrue(PrivateNote.objects.filter(pk=note_id, deleted_at__isnull=True).exists())


class PrivateNoteImageApiTests(OperatorApiTestCase):
    """B-043 阶段4：私有笔记配图的鉴权读回与隔离。"""

    def test_default_private_storage_is_outside_public_media(self):
        from pathlib import Path

        from django.conf import settings
        from django.urls import resolve

        private_root = Path(settings.STORAGES["private_note_media"]["OPTIONS"]["location"]).resolve()
        self.assertFalse(private_root.is_relative_to(Path(settings.MEDIA_ROOT).resolve()))
        self.assertEqual(resolve("/media/private-notes/legacy.png").func.__name__, "deny_legacy_private_media")
        self.assertEqual(self.client.get("/media/private-notes/legacy.png", HTTP_HOST="localhost").status_code, 404)

    def test_legacy_private_media_command_dry_run_then_verified_move(self):
        import hashlib
        from io import StringIO
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from django.conf import settings
        from django.core.management import call_command
        from django.test import override_settings

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            public = root / "public"
            private = root / "private"
            relative = Path(str(self.test_user.pk)) / "legacy.png"
            source = public / "private-notes" / relative
            source.parent.mkdir(parents=True)
            data = self._png()
            source.write_bytes(data)
            image = PrivateNoteImage.objects.create(
                owner=self.test_user,
                workspace_key="default",
                file=str(relative).replace("\\", "/"),
                byte_size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
            storage_settings = {
                **settings.STORAGES,
                "private_note_media": {
                    "BACKEND": "django.core.files.storage.FileSystemStorage",
                    "OPTIONS": {"location": private},
                },
            }
            with override_settings(MEDIA_ROOT=public, STORAGES=storage_settings):
                report = StringIO()
                call_command("migrate_private_note_media", stdout=report)
                self.assertIn("would move: 1", report.getvalue())
                self.assertTrue(source.exists())
                call_command("migrate_private_note_media", "--apply", stdout=StringIO())
                self.assertFalse(source.exists())
                self.assertEqual((private / relative).read_bytes(), data)
                self.assertEqual(PrivateNoteImage.objects.get(pk=image.pk).file.name, relative.as_posix())

    def _png(self):
        from io import BytesIO

        from PIL import Image

        output = BytesIO()
        Image.new("RGB", (2, 2), "red").save(output, format="PNG")
        return output.getvalue()

    def test_upload_readback_and_cross_access(self):
        from django.conf import settings
        from django.test import override_settings

        storages_setting = {
            **settings.STORAGES,
            "private_note_media": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": TEST_MEDIA_ROOT / "private-notes"},
            },
        }
        with override_settings(STORAGES=storages_setting):
            response = self.client.post(
                "/api/agent/blog/notes/images/",
                {"image": SimpleUploadedFile("a.png", self._png(), content_type="image/png")},
                HTTP_HOST="localhost",
            )
            image_id = response.json()["id"]
            # 读回必须走认证接口，而不是 /media/ 公开地址
            url = response.json()["url"]
            self.assertEqual(url, f"/api/agent/blog/notes/images/{image_id}/")
            self.assertNotIn("/media/", url)

            readback = self.client.get(url, HTTP_HOST="localhost")
            self.assertEqual(readback.status_code, 200)
            self.assertEqual(readback["Content-Type"], "image/png")
            self.assertEqual(b"".join(readback.streaming_content), self._png())

            # 匿名不能读
            self.client.defaults.pop("HTTP_AUTHORIZATION")
            anonymous = self.client.get(url, HTTP_HOST="localhost")
            self.assertEqual(anonymous.status_code, 401)

            # 其他用户 404（不暴露存在性）
            other, _ = self.authenticate_test_user("operator")
            other_read = self.client.get(url, HTTP_HOST="localhost")
            self.assertEqual(other_read.status_code, 404)

            # 其他 workspace 404
            self.authenticate_test_user("admin", workspace_key="another-space")
            other_space = self.client.get(url, HTTP_HOST="localhost")
            self.assertEqual(other_space.status_code, 404)

    def test_remote_fetch_failure_keeps_nothing(self):
        from django.conf import settings
        from django.test import override_settings

        from ..services.remote_blog_image import RemoteImageError

        storages_setting = {
            **settings.STORAGES,
            "private_note_media": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": TEST_MEDIA_ROOT / "private-notes"},
            },
        }
        with override_settings(STORAGES=storages_setting):
            with patch("apps.agent_api.views.blog_note_images.fetch_remote_image") as fetch:
                fetch.side_effect = RemoteImageError("原站拒绝下载")
                response = self.client.post(
                    "/api/agent/blog/notes/images/fetch/",
                    json.dumps({"url": "https://example.org/a.png"}),
                    content_type="application/json",
                    HTTP_HOST="localhost",
                )
            self.assertEqual(response.status_code, 422)
            self.assertEqual(PrivateNoteImage.objects.count(), 0)

    def test_bind_and_orphan_cleanup(self):
        from django.conf import settings
        from django.test import override_settings

        storages_setting = {
            **settings.STORAGES,
            "private_note_media": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": TEST_MEDIA_ROOT / "private-notes"},
            },
        }
        with override_settings(STORAGES=storages_setting):
            created = self.client.post(
                "/api/agent/blog/notes/",
                json.dumps({"title": "带图笔记", "content": "正文"}),
                content_type="application/json",
                HTTP_HOST="localhost",
            )
            note_id = created.json()["id"]
            uploaded = self.client.post(
                "/api/agent/blog/notes/images/",
                {"image": SimpleUploadedFile("b.png", self._png(), content_type="image/png")},
                HTTP_HOST="localhost",
            )
            image_id = uploaded.json()["id"]
            bound = self.client.post(
                f"/api/agent/blog/notes/{note_id}/images/bind/",
                json.dumps({"image_ids": [image_id]}),
                content_type="application/json",
                HTTP_HOST="localhost",
            )
            self.assertEqual(bound.status_code, 200)
            self.assertEqual(bound.json()["bound"], 1)
            image = PrivateNoteImage.objects.get(pk=image_id)
            self.assertEqual(image.note_id, note_id)
            # 未绑定且超过 TTL 的孤儿图片可被清理
            self.assertEqual(cleanup_orphan_private_images(), 0)
            image.created_at = timezone.now() - timezone.timedelta(hours=48)
            image.note = None
            image.save()
            self.assertEqual(cleanup_orphan_private_images(), 1)
            self.assertEqual(PrivateNoteImage.objects.count(), 1)
            with patch("apps.agent_api.views.blog_note_images.private_note_storage") as storage:
                storage.return_value.delete.side_effect = OSError("isolated storage failure")
                self.assertEqual(cleanup_orphan_private_images(apply=True), 0)
            self.assertTrue(PrivateNoteImage.objects.filter(pk=image_id).exists())
            self.assertEqual(cleanup_orphan_private_images(apply=True), 1)
            self.assertEqual(PrivateNoteImage.objects.count(), 0)
