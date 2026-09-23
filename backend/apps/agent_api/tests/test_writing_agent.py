"""博客写作助手配置与输出测试。"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase


class BlogWritingAgentTests(TestCase):
    def test_writing_agent_requires_login(self):
        response = self.client.post(
            "/api/agent/blog/writing-agent/generate/",
            {"mode": "task_list", "instruction": "整理写作计划"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 401)

    @patch("apps.agent_api.views.blog.BlogWritingAgent")
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
