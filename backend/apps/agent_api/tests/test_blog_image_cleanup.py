"""Public image cleanup must not remove shared or still-referenced media."""

import os
import uuid
from datetime import timedelta
from io import StringIO
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from ..models import BlogArticle, BlogArticleRevision, PrivateNote, UserProfile
from .support import OperatorApiTestCase


def image_name() -> str:
    return f"{uuid.uuid4().hex}.png"


def image_url(name: str) -> str:
    return f"/media/blog/{name}"


class BlogImageCleanupTests(OperatorApiTestCase):
    def media_settings(self, directory):
        return {
            **settings.STORAGES,
            "blog_media": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
                "OPTIONS": {"location": directory, "base_url": "/media/"},
            },
        }

    def test_approved_delete_removes_only_unreferenced_article_and_revision_images(self):
        with TemporaryDirectory() as directory, override_settings(STORAGES=self.media_settings(directory)):
            storage = storages["blog_media"]
            solo, shared, note_used, revision_used, unrelated = [image_name() for _ in range(5)]
            for name in (solo, shared, note_used, revision_used, unrelated):
                storage.save(f"blog/{name}", ContentFile(b"image"))

            article = BlogArticle.objects.create(
                title="Delete with images",
                slug="delete-with-images",
                author_name=self.test_user.username,
                content=f"![solo]({image_url(solo)}) ![shared]({image_url(shared)})",
                cover_image=image_url(note_used),
            )
            BlogArticleRevision.objects.create(
                article=article,
                base_version=0,
                title="Revision",
                content=f"![rev]({image_url(revision_used)})",
            )
            BlogArticle.objects.create(title="Keep shared", slug="keep-shared", content=image_url(shared))
            PrivateNote.objects.create(
                owner=self.test_user,
                workspace_key=article.workspace_key,
                title="Keep note image",
                content=f"![note]({image_url(note_used)})",
            )

            self.authenticate_test_user(UserProfile.Role.ADMIN)
            request = self.client.delete(f"/api/agent/blog/articles/{article.slug}/", HTTP_HOST="localhost")
            self.assertEqual(request.status_code, 202)
            self.assertTrue(storage.exists(f"blog/{solo}"))  # Approval is not deletion.
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    f"/api/agent/approvals/{request.json()['approval']['id']}/",
                    {"decision": "approve", "reviewer": "admin"},
                    content_type="application/json",
                    HTTP_HOST="localhost",
                )
            self.assertEqual(response.status_code, 200)
            self.assertFalse(BlogArticle.objects.filter(pk=article.pk).exists())
            self.assertFalse(storage.exists(f"blog/{solo}"))
            self.assertFalse(storage.exists(f"blog/{revision_used}"))
            for name in (shared, note_used, unrelated):
                self.assertTrue(storage.exists(f"blog/{name}"), name)

    def test_orphan_command_previews_then_deletes_only_old_unreferenced_files(self):
        with TemporaryDirectory() as directory, override_settings(STORAGES=self.media_settings(directory)):
            storage = storages["blog_media"]
            old_orphan, old_shared, recent_orphan = [image_name() for _ in range(3)]
            for name in (old_orphan, old_shared, recent_orphan):
                storage.save(f"blog/{name}", ContentFile(b"image"))
            BlogArticle.objects.create(title="Keep", slug="keep-media", content=image_url(old_shared))
            old_timestamp = (timezone.now() - timedelta(days=45)).timestamp()
            for name in (old_orphan, old_shared):
                os.utime(storage.path(f"blog/{name}"), (old_timestamp, old_timestamp))

            preview = StringIO()
            call_command("prune_blog_media", stdout=preview)
            self.assertIn("mode: preview", preview.getvalue())
            self.assertIn(f"blog/{old_orphan}", preview.getvalue())
            self.assertNotIn(f"blog/{old_shared}", preview.getvalue())
            self.assertTrue(storage.exists(f"blog/{old_orphan}"))

            call_command("prune_blog_media", apply=True, stdout=StringIO())
            self.assertFalse(storage.exists(f"blog/{old_orphan}"))
            self.assertTrue(storage.exists(f"blog/{old_shared}"))
            self.assertTrue(storage.exists(f"blog/{recent_orphan}"))
