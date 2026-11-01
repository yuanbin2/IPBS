"""Media reconciliation must detect loss without changing user data."""

import io
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management import call_command
from django.test import TestCase, override_settings

from ..management.commands.audit_media_references import audit_media_references
from ..models import BlogArticle, Document, KnowledgeBase, PrivateNoteImage


class MediaAuditTests(TestCase):
    def test_missing_and_orphans_are_reported_without_deletion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            storage_config = {
                "default": {
                    "BACKEND": "django.core.files.storage.FileSystemStorage",
                    "OPTIONS": {"location": root / "media"},
                },
                "blog_media": {
                    "BACKEND": "django.core.files.storage.FileSystemStorage",
                    "OPTIONS": {"location": root / "media"},
                },
                "private_note_media": {
                    "BACKEND": "django.core.files.storage.FileSystemStorage",
                    "OPTIONS": {"location": root / "private"},
                },
            }
            with override_settings(STORAGES=storage_config):
                name = "a" * 32 + ".png"
                BlogArticle.objects.create(title="audit", slug="audit", content=f"/media/blog/{name}")
                user = get_user_model().objects.create_user(username="audit")
                PrivateNoteImage.objects.create(owner=user, workspace_key="default", file="1/missing.png")
                kb = KnowledgeBase.objects.create(name="audit")
                Document.objects.create(knowledge_base=kb, title="audit", source_file="knowledge/missing.txt")
                storages["blog_media"].save("blog/" + "b" * 32 + ".png", ContentFile(b"orphan"))
                storages["private_note_media"].save("1/orphan.png", ContentFile(b"orphan"))
                storages["default"].save("knowledge/orphan.txt", ContentFile(b"orphan"))

                audit = audit_media_references()
                self.assertEqual([len(audit[k].missing) for k in ("public", "private", "source")], [1, 1, 1])
                self.assertEqual([len(audit[k].orphan) for k in ("public", "private", "source")], [1, 1, 1])
                output = io.StringIO()
                call_command("audit_media_references", stdout=output)
                self.assertIn("public: missing=1 orphan=1", output.getvalue())
                self.assertIn("Read-only audit", output.getvalue())
                self.assertTrue(storages["private_note_media"].exists("1/orphan.png"))
