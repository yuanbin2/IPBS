"""Comment/report account restrictions are separate from article access."""

from datetime import timedelta

from django.utils import timezone

from ..models import BlogArticle, BlogComment, BlogInteractionRestriction, SecurityAuditEvent, UserProfile
from .support import OperatorApiTestCase


class BlogInteractionRestrictionTests(OperatorApiTestCase):
    list_url = "/api/agent/blog/comment-restrictions/"
    own_url = "/api/agent/blog/comment-restriction/me/"
    appeal_url = "/api/agent/blog/comment-restriction/appeal/"

    def setUp(self):
        super().setUp()
        self.admin, self.admin_token = self.authenticate_test_user(UserProfile.Role.ADMIN)
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {self.test_token}"
        self.article = BlogArticle.objects.create(
            title="Moderated", slug="moderated", content="Public body", status=BlogArticle.Status.PUBLISHED
        )
        self.comment = BlogComment.objects.create(
            article=self.article, author_name="reader", content="visible", is_approved=True, is_reviewed=True
        )

    def as_admin(self):
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {self.admin_token}"

    def as_operator(self):
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {self.test_token}"

    def restrict(self, *, days=3):
        self.as_admin()
        return self.client.post(
            self.list_url,
            {"username": self.test_user.username, "reason": "Repeated spam after warning", "days": days},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

    def test_restriction_blocks_only_comment_and_report_then_expires(self):
        created = self.restrict()
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.json()["active"])
        self.assertEqual(SecurityAuditEvent.objects.filter(event_type="blog_interaction_restricted").count(), 1)
        self.as_operator()
        self.assertEqual(
            self.client.get(self.own_url, HTTP_HOST="localhost").json()["restriction"]["reason"],
            "Repeated spam after warning",
        )
        comment_url = f"/api/agent/blog/articles/{self.article.slug}/comments/"
        report_url = f"/api/agent/blog/comments/{self.comment.pk}/reports/"
        blocked_comment = self.client.post(
            comment_url, {"content": "new comment"}, content_type="application/json", HTTP_HOST="localhost"
        )
        blocked_report = self.client.post(
            report_url, {"reason": "spam"}, content_type="application/json", HTTP_HOST="localhost"
        )
        self.assertEqual(blocked_comment.status_code, 403)
        self.assertIn("申诉", blocked_comment.content.decode())
        self.assertEqual(blocked_report.status_code, 403)
        self.assertEqual(BlogComment.objects.count(), 1)
        self.assertEqual(self.client.get(comment_url, HTTP_HOST="localhost").status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/agent/blog/articles/{self.article.slug}/", HTTP_HOST="localhost").status_code,
            200,
        )
        restriction = BlogInteractionRestriction.objects.get(pk=created.json()["id"])
        restriction.expires_at = timezone.now() - timedelta(minutes=1)
        restriction.save(update_fields=["expires_at"])
        self.assertIsNone(self.client.get(self.own_url, HTTP_HOST="localhost").json()["restriction"])
        allowed = self.client.post(
            comment_url, {"content": "new comment"}, content_type="application/json", HTTP_HOST="localhost"
        )
        self.assertEqual(allowed.status_code, 201)

    def test_appeal_acceptance_and_manual_lift_are_audited(self):
        created = self.restrict()
        restriction_id = created.json()["id"]
        self.as_operator()
        appeal = self.client.post(
            self.appeal_url,
            {"message": "I understand the rules and will stop repeating comments."},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(appeal.status_code, 201)
        self.assertEqual(appeal.json()["appeal_status"], "pending")
        self.assertEqual(
            self.client.post(
                self.appeal_url,
                {"message": "Please reconsider this comment restriction."},
                content_type="application/json",
                HTTP_HOST="localhost",
            ).status_code,
            409,
        )
        self.as_admin()
        listed = self.client.get(self.list_url, HTTP_HOST="localhost").json()
        self.assertEqual(listed[0]["appeal_status"], "pending")
        accepted = self.client.post(
            f"{self.list_url}{restriction_id}/",
            {"action": "accept_appeal"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertFalse(accepted.json()["active"])
        self.assertEqual(accepted.json()["appeal_status"], "accepted")
        self.assertFalse(
            self.client.post(
                f"{self.list_url}{restriction_id}/",
                {"action": "lift"},
                content_type="application/json",
                HTTP_HOST="localhost",
            ).json()["changed"]
        )
        self.assertEqual(SecurityAuditEvent.objects.filter(event_type="blog_interaction_appealed").count(), 1)
        self.assertEqual(SecurityAuditEvent.objects.filter(event_type="blog_interaction_appeal_reviewed").count(), 1)
        self.as_operator()
        self.assertIsNone(self.client.get(self.own_url, HTTP_HOST="localhost").json()["restriction"])
        self.assertEqual(
            self.client.post(
                f"/api/agent/blog/articles/{self.article.slug}/comments/",
                {"content": "allowed after appeal"},
                content_type="application/json",
                HTTP_HOST="localhost",
            ).status_code,
            201,
        )

    def test_upheld_appeal_stays_restricted_until_lift(self):
        restriction_id = self.restrict().json()["id"]
        self.as_operator()
        self.client.post(
            self.appeal_url,
            {"message": "I dispute the moderation decision."},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.as_admin()
        upheld = self.client.post(
            f"{self.list_url}{restriction_id}/",
            {"action": "uphold_appeal"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(upheld.status_code, 200)
        self.assertTrue(upheld.json()["active"])
        self.assertEqual(upheld.json()["appeal_status"], "upheld")
        lifted = self.client.post(
            f"{self.list_url}{restriction_id}/",
            {"action": "lift"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(lifted.status_code, 200)
        self.assertFalse(lifted.json()["active"])
        self.assertEqual(SecurityAuditEvent.objects.filter(event_type="blog_interaction_lifted").count(), 1)

    def test_restriction_is_scoped_to_original_workspace(self):
        self.assertEqual(self.restrict().status_code, 201)
        self.test_user.agent_profile.workspace_key = "other"
        self.test_user.agent_profile.save(update_fields=["workspace_key"])
        other_article = BlogArticle.objects.create(
            title="Other workspace",
            slug="other-workspace",
            workspace_key="other",
            content="Public",
            status=BlogArticle.Status.PUBLISHED,
        )
        self.as_operator()
        self.assertIsNone(self.client.get(self.own_url, HTTP_HOST="localhost").json()["restriction"])
        response = self.client.post(
            f"/api/agent/blog/articles/{other_article.slug}/comments/",
            {"content": "Allowed in other workspace"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 201)

    def test_management_requires_real_admin_jwt_and_workspace(self):
        self.assertEqual(self.client.get(self.list_url, HTTP_HOST="localhost").status_code, 403)
        self.client.defaults.pop("HTTP_AUTHORIZATION", None)
        self.client.defaults["HTTP_X_ROLE"] = "admin"
        self.assertEqual(self.client.get(self.list_url, HTTP_HOST="localhost").status_code, 401)
        self.client.defaults.pop("HTTP_X_ROLE", None)
        self.as_admin()
        other_admin, other_token = self.authenticate_test_user(UserProfile.Role.ADMIN, workspace_key="other")
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {other_token}"
        self.assertEqual(self.client.get(self.list_url, HTTP_HOST="localhost").json(), [])
        self.assertEqual(
            self.client.post(
                self.list_url,
                {"username": self.test_user.username, "reason": "Repeated spam after warning", "days": 3},
                content_type="application/json",
                HTTP_HOST="localhost",
            ).status_code,
            404,
        )
        self.assertEqual(self.restrict().status_code, 201)
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {other_token}"
        self.assertEqual(self.client.get(self.list_url, HTTP_HOST="localhost").json(), [])
        self.assertEqual(
            self.client.post(
                f"{self.list_url}1/", {"action": "lift"}, content_type="application/json", HTTP_HOST="localhost"
            ).status_code,
            404,
        )
        self.assertNotEqual(other_admin.pk, self.admin.pk)

    def test_invalid_targets_duration_and_appeal_are_rejected(self):
        self.as_operator()
        self.assertEqual(
            self.client.post(
                self.appeal_url,
                {"message": "No restriction yet"},
                content_type="application/json",
                HTTP_HOST="localhost",
            ).status_code,
            404,
        )
        self.as_admin()
        for payload in (
            {"username": self.test_user.username, "reason": "short", "days": 3},
            {"username": self.test_user.username, "reason": "Repeated spam after warning", "days": 31},
            {"username": self.admin.username, "reason": "Repeated spam after warning", "days": 3},
        ):
            response = self.client.post(self.list_url, payload, content_type="application/json", HTTP_HOST="localhost")
            self.assertIn(response.status_code, {400, 403})
        self.assertEqual(BlogInteractionRestriction.objects.count(), 0)
