import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from agent.simple_agent import SimpleToolCallingAgent

from .models import AgentRun, Conversation, Document, DocumentChunk, EmbeddingRecord, KnowledgeBase, Message
from .rag import LOCAL_EMBEDDING_MODEL, search_knowledge_base


NO_MODEL_ENV = {
    "OPENAI_API_KEY": "",
    "OPENAI_EMBEDDING_API_KEY": "",
    "BAILIAN_API_KEY": "",
    "DASHSCOPE_API_KEY": "",
    "LANGSMITH_TRACING": "false",
    "LANGCHAIN_TRACING_V2": "false",
}

TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "knowledge_agent_test_media"


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
        self.assertIn("sources", payload)
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
        self.assertEqual(payload["sources"], [])
        self.assertNotIn("数据库中没有", payload["answer"])

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
        self.assertIn("sources", payload["messages"][1])

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

        self.assertEqual(
            [item["content"] for item in latest_payload["messages"]],
            ["message 5", "message 6", "message 7"],
        )
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

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_document_upload_creates_chunks_and_embeddings(self):
        upload = SimpleUploadedFile(
            "rag-notes.txt",
            (
                "LangGraph controls agent state transitions.\n\n"
                "RAG retrieves knowledge chunks and passes them into the final model prompt."
            ).encode("utf-8"),
            content_type="text/plain",
        )

        response = self.client.post(
            "/api/agent/documents/",
            {"file": upload, "title": "RAG Notes"},
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["status"], Document.Status.READY)
        self.assertGreaterEqual(payload["chunk_count"], 1)
        self.assertEqual(KnowledgeBase.objects.count(), 1)
        self.assertEqual(DocumentChunk.objects.count(), payload["chunk_count"])
        self.assertEqual(EmbeddingRecord.objects.count(), payload["chunk_count"])

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_knowledge_search_returns_relevant_chunks(self):
        upload = SimpleUploadedFile(
            "knowledge.txt",
            (
                "Agentic RAG means the agent retrieves context first.\n\n"
                "The retrieved context is inserted into the prompt before the model answers."
            ).encode("utf-8"),
            content_type="text/plain",
        )
        self.client.post(
            "/api/agent/documents/",
            {"file": upload, "title": "Agentic RAG"},
            HTTP_HOST="localhost",
        )

        response = self.client.post(
            "/api/agent/knowledge-search/",
            {"query": "retrieved context prompt", "limit": 3},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(len(payload), 1)
        self.assertEqual(payload[0]["document_title"], "Agentic RAG")

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_knowledge_search_uses_keyword_signal_when_vectors_are_weak(self):
        knowledge_base = KnowledgeBase.objects.create(name="hybrid")
        document = Document.objects.create(
            knowledge_base=knowledge_base,
            title="LangGraph RAG Notes",
            status=Document.Status.READY,
        )
        weak_chunk = DocumentChunk.objects.create(
            document=document,
            knowledge_base=knowledge_base,
            chunk_index=0,
            content="This paragraph is about generic platform setup.",
        )
        strong_chunk = DocumentChunk.objects.create(
            document=document,
            knowledge_base=knowledge_base,
            chunk_index=1,
            content="Agentic RAG stores retrieved context inside the final prompt before answering.",
        )
        EmbeddingRecord.objects.create(
            chunk=weak_chunk,
            model=LOCAL_EMBEDDING_MODEL,
            vector=[0.0, 0.0, 0.0],
            vector_dimensions=3,
        )
        EmbeddingRecord.objects.create(
            chunk=strong_chunk,
            model=LOCAL_EMBEDDING_MODEL,
            vector=[0.0, 0.0, 0.0],
            vector_dimensions=3,
        )

        results = search_knowledge_base("retrieved context prompt", knowledge_base_id=knowledge_base.id, limit=2)

        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].chunk_id, strong_chunk.id)

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_document_reindex_rebuilds_chunks(self):
        upload = SimpleUploadedFile(
            "reindex.txt",
            "RAG reindex should rebuild document chunks.".encode("utf-8"),
            content_type="text/plain",
        )
        upload_response = self.client.post(
            "/api/agent/documents/",
            {"file": upload, "title": "Reindex"},
            HTTP_HOST="localhost",
        )
        document_id = upload_response.json()["id"]

        response = self.client.post(
            f"/api/agent/documents/{document_id}/reindex/",
            {},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], Document.Status.READY)
        self.assertGreaterEqual(response.json()["chunk_count"], 1)

    @patch.dict("os.environ", {**NO_MODEL_ENV, "OPENAI_API_KEY": "test-key"})
    def test_agentic_retrieve_returns_tool_call_and_sources_key(self):
        agent = SimpleToolCallingAgent(Path(settings.BASE_DIR).parent)

        state = agent._retrieve(
            {
                "message": "请根据知识库回答 RAG 是什么",
                "query": "请根据知识库回答 RAG 是什么",
                "tool_calls": [],
                "sources": [],
                "trace": [],
                "token_usage": agent._empty_token_usage(),
            }
        )

        self.assertGreaterEqual(len(state["tool_calls"]), 1)
        self.assertEqual(state["tool_calls"][0].name, "knowledge_search")
        self.assertIn("sources", state)
