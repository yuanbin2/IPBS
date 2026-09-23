"""文档生命周期：上传、内联降级、pgvector 同步、重建与删除。"""

from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from ..models import ApprovalRequest, Document, DocumentChunk, EmbeddingRecord, KnowledgeBase
from ..services.rag import LOCAL_EMBEDDING_DIMENSIONS, LOCAL_EMBEDDING_MODEL
from ..services.vector_store import vector_literal
from .support import NO_MODEL_ENV, TEST_MEDIA_ROOT


class DocumentLifecycleTests(TestCase):

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_document_upload_creates_chunks_and_embeddings(self):
        upload = SimpleUploadedFile(
            "rag-notes.txt",
            (
                b"LangGraph controls agent state transitions.\n\n"
                b"RAG retrieves knowledge chunks and passes them into the final model prompt."
            ),
            content_type="text/plain",
        )

        response = self.client.post(
            "/api/agent/documents/",
            {"file": upload, "title": "RAG Notes"},
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertIn("task_id", payload)
        self.assertEqual(payload["task_state"], "SUCCESS")
        self.assertNotIn("task_url", payload)
        document = Document.objects.get(pk=payload["id"])
        self.assertEqual(document.status, Document.Status.READY)
        self.assertGreaterEqual(document.chunk_count, 1)
        self.assertEqual(KnowledgeBase.objects.count(), 1)
        self.assertEqual(DocumentChunk.objects.count(), document.chunk_count)
        self.assertEqual(EmbeddingRecord.objects.count(), document.chunk_count)

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CELERY_TASK_ALWAYS_EAGER=False, DEBUG=True)
    @patch.dict("os.environ", NO_MODEL_ENV)
    @patch("apps.agent_api.views.knowledge.ingest_document_task.delay", side_effect=ConnectionError("broker down"))
    def test_document_upload_falls_back_to_inline_processing_when_broker_is_unavailable(self, _delay):
        upload = SimpleUploadedFile(
            "local-upload.txt",
            b"Local development upload should work without a broker.",
            content_type="text/plain",
        )

        response = self.client.post(
            "/api/agent/documents/",
            {"file": upload, "title": "Local Upload"},
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["task_state"], "SUCCESS")
        self.assertNotIn("task_url", payload)
        _delay.assert_not_called()
        document = Document.objects.get(pk=payload["id"])
        self.assertEqual(document.status, Document.Status.READY)
        self.assertGreaterEqual(document.chunk_count, 1)

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    @patch.dict("os.environ", NO_MODEL_ENV)
    @patch("apps.agent_api.services.rag.ingest.upsert_chunk_vector")
    @patch("apps.agent_api.services.rag.ingest.should_use_pgvector", return_value=True)
    def test_document_ingestion_syncs_vectors_to_pgvector_store(self, _should_use_pgvector, mocked_upsert):
        upload = SimpleUploadedFile(
            "pgvector-sync.txt",
            b"This document should be embedded and written to the vector store.",
            content_type="text/plain",
        )

        response = self.client.post(
            "/api/agent/documents/",
            {"file": upload, "title": "pgvector sync"},
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 202)
        document = Document.objects.get(pk=response.json()["id"])
        self.assertEqual(document.status, Document.Status.READY)
        self.assertGreaterEqual(mocked_upsert.call_count, 1)
        record = EmbeddingRecord.objects.get(chunk__document=document)
        self.assertEqual(record.vector, [])
        self.assertEqual(record.vector_dimensions, LOCAL_EMBEDDING_DIMENSIONS)

    def test_vector_literal_formats_pgvector_input(self):
        self.assertEqual(vector_literal([0, 0.25, -1.5]), "[0,0.25,-1.5]")

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_document_reindex_rebuilds_chunks(self):
        upload = SimpleUploadedFile(
            "reindex.txt",
            b"RAG reindex should rebuild document chunks.",
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

        self.assertEqual(response.status_code, 202)
        self.assertIn("task_id", response.json())
        document = Document.objects.get(pk=document_id)
        self.assertEqual(document.status, Document.Status.READY)
        self.assertGreaterEqual(document.chunk_count, 1)

    def test_document_delete_removes_chunks_and_embeddings(self):
        knowledge_base = KnowledgeBase.objects.create(name="delete-doc")
        document = Document.objects.create(
            knowledge_base=knowledge_base,
            title="Delete Me",
            status=Document.Status.READY,
        )
        chunk = DocumentChunk.objects.create(
            document=document,
            knowledge_base=knowledge_base,
            chunk_index=0,
            content="content to delete",
        )
        EmbeddingRecord.objects.create(
            chunk=chunk,
            model=LOCAL_EMBEDDING_MODEL,
            vector=[0.1, 0.2],
            vector_dimensions=2,
        )

        response = self.client.delete(
            f"/api/agent/documents/{document.id}/",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 202)
        approval_id = response.json()["approval"]["id"]
        self.assertEqual(ApprovalRequest.objects.get(pk=approval_id).action, ApprovalRequest.Action.DELETE_DOCUMENT)
        self.assertEqual(Document.objects.count(), 1)

        approve_response = self.client.post(
            f"/api/agent/approvals/{approval_id}/",
            {"decision": "approve", "reviewer": "admin"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(approve_response.status_code, 200)
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(DocumentChunk.objects.count(), 0)
        self.assertEqual(EmbeddingRecord.objects.count(), 0)

    def test_knowledge_base_delete_removes_documents(self):
        knowledge_base = KnowledgeBase.objects.create(name="delete-base")
        Document.objects.create(
            knowledge_base=knowledge_base,
            title="Document in deleted base",
            status=Document.Status.READY,
        )

        response = self.client.delete(
            f"/api/agent/knowledge-bases/{knowledge_base.id}/",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 202)
        approval_id = response.json()["approval"]["id"]
        self.assertEqual(KnowledgeBase.objects.count(), 1)

        approve_response = self.client.post(
            f"/api/agent/approvals/{approval_id}/",
            {"decision": "approve", "reviewer": "admin"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(approve_response.status_code, 200)
        self.assertEqual(KnowledgeBase.objects.count(), 0)
        self.assertEqual(Document.objects.count(), 0)
