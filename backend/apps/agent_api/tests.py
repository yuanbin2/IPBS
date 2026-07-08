from unittest.mock import patch

from django.test import TestCase

from .models import AgentRun, Conversation, Message


NO_MODEL_ENV = {
    "OPENAI_API_KEY": "",
    "LANGSMITH_TRACING": "false",
    "LANGCHAIN_TRACING_V2": "false",
}


class AgentChatTests(TestCase):
    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_agent_chat_uses_calculator_tool_and_persists_history(self):
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
        self.assertIn("total_tokens", payload["token_usage"])
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(Message.objects.count(), 2)
        self.assertEqual(AgentRun.objects.count(), 1)

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_agent_chat_tells_joke_without_searching_database(self):
        response = self.client.post(
            "/api/agent/chat/",
            {"message": "说一个笑话"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["route"], "direct")
        self.assertEqual(payload["tool_calls"], [])
        self.assertNotIn("没有在本地", payload["answer"])

    def test_agent_chat_requires_message(self):
        response = self.client.post(
            "/api/agent/chat/",
            {},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 400)

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_conversation_detail_returns_messages(self):
        chat_response = self.client.post(
            "/api/agent/chat/",
            {"message": "帮我计算 3 + 5"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        conversation_id = chat_response.json()["conversation"]["id"]

        response = self.client.get(
            f"/api/agent/conversations/{conversation_id}/",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["id"], conversation_id)
        self.assertEqual(len(payload["messages"]), 2)

    def test_conversation_detail_limits_messages_and_loads_older(self):
        conversation = Conversation.objects.create(title="paged history")
        for index in range(8):
            Message.objects.create(
                conversation=conversation,
                role=Message.Role.USER,
                content=f"message {index}",
            )

        latest_response = self.client.get(
            f"/api/agent/conversations/{conversation.id}/?limit=3",
            HTTP_HOST="localhost",
        )
        latest_payload = latest_response.json()

        self.assertEqual([item["content"] for item in latest_payload["messages"]], ["message 5", "message 6", "message 7"])
        self.assertTrue(latest_payload["has_more_before"])

        oldest_id = latest_payload["messages"][0]["id"]
        older_response = self.client.get(
            f"/api/agent/conversations/{conversation.id}/?limit=3&before={oldest_id}",
            HTTP_HOST="localhost",
        )

        self.assertEqual(
            [item["content"] for item in older_response.json()["messages"]],
            ["message 2", "message 3", "message 4"],
        )

    def test_conversation_search_returns_matched_message_id(self):
        conversation = Conversation.objects.create(title="searchable")
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.USER,
            content="normal message",
        )
        matched = Message.objects.create(
            conversation=conversation,
            role=Message.Role.AGENT,
            content="contains unique keyword",
        )

        response = self.client.get(
            "/api/agent/conversations/?q=unique",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["matched_message_id"], matched.id)
