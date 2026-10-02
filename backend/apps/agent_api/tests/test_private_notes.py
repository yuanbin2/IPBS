"""Private notes stay tied to a real user and workspace and never publish."""

from django.utils import timezone

from ..models import BlogArticle, PrivateNote, UserProfile
from .support import OperatorApiTestCase


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
        listed = self.client.get(
            f"{self.notes_url}?source_article={article.id}", HTTP_HOST="localhost"
        )
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
