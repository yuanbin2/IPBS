from unittest.mock import patch

from django.test import SimpleTestCase


class AgentChatTests(SimpleTestCase):
    @patch.dict("os.environ", {"OPENAI_API_KEY": ""})
    def test_agent_chat_uses_calculator_tool(self):
        response = self.client.post(
            "/api/agent/chat/",
            {"message": "帮我计算 12 * 8"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("96", payload["answer"])
        self.assertEqual(payload["tool_calls"][0]["name"], "calculator")

    def test_agent_chat_requires_message(self):
        response = self.client.post(
            "/api/agent/chat/",
            {},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 400)

