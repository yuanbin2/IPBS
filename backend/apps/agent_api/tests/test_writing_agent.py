"""博客写作助手配置与输出测试。"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from redis.exceptions import RedisError

from ..models import PrivateNote, UserProfile
from .support import OperatorApiTestCase, SecurityTransportTestCase


class BlogWritingAgentTests(SecurityTransportTestCase):
    def test_writing_agent_requires_login(self):
        response = self.client.post(
            "/api/agent/blog/writing-agent/generate/",
            {"mode": "task_list", "instruction": "整理写作计划"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 401)

    @patch("apps.agent_api.views.blog_writing.BlogWritingAgent")
    def test_writing_agent_returns_markdown_for_authenticated_author(self, mocked_agent):
        from rest_framework_simplejwt.tokens import RefreshToken

        from ..services.writing_agent import WritingAgentResult

        user = get_user_model().objects.create_user(username="writer", password="secret-pass")
        access_token = str(RefreshToken.for_user(user).access_token)
        mocked_agent.return_value.generate.return_value = WritingAgentResult(
            markdown="## 写作任务\n\n- [ ] 整理资料",
            mode="task_list",
            model="test-model",
            api_key_source="shared",
        )

        response = self.client.post(
            "/api/agent/blog/writing-agent/generate/",
            {
                "mode": "task_list",
                "instruction": "整理写作计划",
                "draft": {"title": "Agent 笔记", "content": "## 背景"},
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("- [ ]", payload["markdown"])
        self.assertEqual(payload["api_key_source"], "shared")
        mocked_agent.return_value.generate.assert_called_once()

    @patch("apps.agent_api.services.writing_agent.ChatOpenAI")
    @patch.dict(
        "os.environ",
        {
            "BLOG_WRITING_AGENT_API_KEY": "",
            "BLOG_WRITING_AGENT_BASE_URL": "",
            "BLOG_WRITING_AGENT_MODEL": "",
            "OPENAI_API_KEY": "shared-key",
            "OPENAI_BASE_URL": "https://example.test/v1",
            "OPENAI_MODEL": "shared-model",
        },
    )
    def test_writing_agent_falls_back_to_existing_openai_configuration(self, mocked_chat_openai):
        from ..services.writing_agent import BlogWritingAgent

        agent = BlogWritingAgent()

        self.assertEqual(agent.api_key_source, "shared")
        self.assertEqual(agent.model, "shared-model")
        mocked_chat_openai.assert_called_once_with(
            model="shared-model",
            api_key="shared-key",
            base_url="https://example.test/v1",
            temperature=0.35,
        )

    @patch("apps.agent_api.services.writing_agent.ChatOpenAI")
    @patch.dict(
        "os.environ",
        {
            "BLOG_WRITING_AGENT_API_KEY": "dedicated-key",
            "BLOG_WRITING_AGENT_BASE_URL": "https://writer.example.test/v1",
            "BLOG_WRITING_AGENT_MODEL": "writer-model",
            "OPENAI_API_KEY": "shared-key",
            "OPENAI_BASE_URL": "https://shared.example.test/v1",
            "OPENAI_MODEL": "shared-model",
        },
    )
    def test_writing_agent_prefers_its_dedicated_configuration(self, mocked_chat_openai):
        from ..services.writing_agent import BlogWritingAgent

        agent = BlogWritingAgent()

        self.assertEqual(agent.api_key_source, "dedicated")
        self.assertEqual(agent.model, "writer-model")
        mocked_chat_openai.assert_called_once_with(
            model="writer-model",
            api_key="dedicated-key",
            base_url="https://writer.example.test/v1",
            temperature=0.35,
        )

    def test_writing_agent_removes_outer_markdown_fence(self):
        from ..services.writing_agent import BlogWritingAgent

        cleaned = BlogWritingAgent._clean_markdown("```markdown\n## 标题\n\n正文\n```")

        self.assertEqual(cleaned, "## 标题\n\n正文")


class NoteSummaryApiTests(OperatorApiTestCase):
    url = "/api/agent/blog/writing-agent/generate/"

    def setUp(self):
        super().setUp()
        cache.delete(f"blog-note-summary-hour:{self.test_user.pk}")

    @patch("apps.agent_api.views.blog_writing.BlogWritingAgent")
    def test_summary_reads_owned_notes_only_and_returns_sources(self, mocked_agent):
        from ..services.writing_agent import WritingAgentResult

        first = PrivateNote.objects.create(
            owner=self.test_user, workspace_key="default", title="Architecture", content="PostgreSQL holds the article"
        )
        second = PrivateNote.objects.create(
            owner=self.test_user,
            workspace_key="default",
            title="Tradeoff",
            quote="Keep source IDs",
            content="Review AI output",
        )
        mocked_agent.return_value.generate.return_value = WritingAgentResult(
            markdown=f"## 汇总\n\n- 数据库 [笔记#{first.id}]",
            mode="note_summary",
            model="mock-writer",
            api_key_source="shared",
        )
        response = self.client.post(
            self.url,
            {
                "mode": "note_summary",
                "note_ids": [second.id, first.id],
                "draft": {"content": "客户端伪造的其他私人材料"},
            },
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["model"], "mock-writer")
        self.assertEqual([source["note_id"] for source in payload["sources"]], [second.id, first.id])
        self.assertFalse(payload["truncated"])
        self.assertTrue(payload["generated_at"])
        draft = mocked_agent.return_value.generate.call_args.kwargs["draft"]
        self.assertIn(f"[笔记#{first.id}]", draft["content"])
        self.assertIn("Review AI output", draft["content"])
        self.assertNotIn("客户端伪造", draft["content"])

    @patch("apps.agent_api.views.blog_writing.BlogWritingAgent")
    def test_summary_rejects_foreign_deleted_and_cross_workspace_notes_without_model_call(self, mocked_agent):
        own = PrivateNote.objects.create(owner=self.test_user, workspace_key="default", title="Mine", content="Private")
        deleted = PrivateNote.objects.create(
            owner=self.test_user, workspace_key="default", title="Deleted", content="Hidden", deleted_at=timezone.now()
        )
        other_user, _ = self.authenticate_test_user(UserProfile.Role.ADMIN)
        other = PrivateNote.objects.create(owner=other_user, workspace_key="default", title="Other", content="Secret")
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {self.test_token}"
        for note_ids in ([other.id], [deleted.id], [own.id, other.id]):
            response = self.client.post(
                self.url,
                {"mode": "note_summary", "note_ids": note_ids},
                content_type="application/json",
                HTTP_HOST="localhost",
            )
            self.assertEqual(response.status_code, 404)
        self.test_user.agent_profile.workspace_key = "changed"
        self.test_user.agent_profile.save(update_fields=["workspace_key"])
        response = self.client.post(
            self.url,
            {"mode": "note_summary", "note_ids": [own.id]},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 404)
        mocked_agent.assert_not_called()

    @patch("apps.agent_api.views.blog_writing.BlogWritingAgent")
    def test_summary_validates_selection_empty_notes_and_truncation(self, mocked_agent):
        from ..services.writing_agent import WritingAgentResult

        note = PrivateNote.objects.create(
            owner=self.test_user, workspace_key="default", title="Long", content="x" * 8000
        )
        empty = PrivateNote.objects.create(owner=self.test_user, workspace_key="default", title="Empty")
        for note_ids in ([], [note.id, note.id], list(range(1, 12)), ["1"]):
            response = self.client.post(
                self.url,
                {"mode": "note_summary", "note_ids": note_ids},
                content_type="application/json",
                HTTP_HOST="localhost",
            )
            self.assertEqual(response.status_code, 400)
        response = self.client.post(
            self.url,
            {"mode": "note_summary", "note_ids": [empty.id]},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            self.url,
            {"mode": "note_summary", "note_ids": [note.id, empty.id]},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 400)
        mocked_agent.return_value.generate.return_value = WritingAgentResult(
            markdown="## 摘要", mode="note_summary", model="mock", api_key_source="shared"
        )
        response = self.client.post(
            self.url,
            {"mode": "note_summary", "note_ids": [note.id]},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["truncated"])
        self.assertEqual(response.json()["sources"][0]["included_chars"], 4000)
        self.assertLessEqual(len(mocked_agent.return_value.generate.call_args.kwargs["draft"]["content"]), 4200)

    @patch("apps.agent_api.views.blog_writing.BlogWritingAgent")
    def test_summary_limits_model_calls_per_user(self, mocked_agent):
        from ..services.writing_agent import WritingAgentResult

        note = PrivateNote.objects.create(owner=self.test_user, workspace_key="default", title="Mine", content="text")
        mocked_agent.return_value.generate.return_value = WritingAgentResult(
            markdown="## 摘要", mode="note_summary", model="mock", api_key_source="shared"
        )
        for _ in range(10):
            response = self.client.post(
                self.url,
                {"mode": "note_summary", "note_ids": [note.id]},
                content_type="application/json",
                HTTP_HOST="localhost",
            )
            self.assertEqual(response.status_code, 200)
        response = self.client.post(
            self.url,
            {"mode": "note_summary", "note_ids": [note.id]},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(mocked_agent.return_value.generate.call_count, 10)

    def test_summary_rejects_non_object_json(self):
        response = self.client.post(self.url, "[]", content_type="application/json", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 400)

    @patch("apps.agent_api.views.blog_writing.cache.add", side_effect=RedisError("cache down"))
    @patch("apps.agent_api.views.blog_writing.BlogWritingAgent")
    def test_summary_fails_closed_when_cache_is_unavailable(self, mocked_agent, _mocked_add):
        note = PrivateNote.objects.create(owner=self.test_user, workspace_key="default", title="Mine", content="text")
        response = self.client.post(
            self.url,
            {"mode": "note_summary", "note_ids": [note.id]},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("cache down", response.content.decode())
        mocked_agent.assert_not_called()

    @patch("apps.agent_api.views.blog_writing.BlogWritingAgent")
    def test_summary_model_errors_do_not_expose_note_content(self, mocked_agent):
        note = PrivateNote.objects.create(
            owner=self.test_user, workspace_key="default", title="Secret", content="private-secret-123"
        )
        mocked_agent.return_value.generate.side_effect = RuntimeError("private-secret-123")
        response = self.client.post(
            self.url,
            {"mode": "note_summary", "note_ids": [note.id]},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("private-secret-123", response.content.decode())

    def test_summary_requires_real_jwt_even_when_dev_role_header_exists(self):
        self.client.defaults.pop("HTTP_AUTHORIZATION")
        self.client.defaults["HTTP_X_ROLE"] = "operator"
        response = self.client.post(
            self.url, {"mode": "note_summary", "note_ids": [1]}, content_type="application/json", HTTP_HOST="localhost"
        )
        self.assertEqual(response.status_code, 401)
