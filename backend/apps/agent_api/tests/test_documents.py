"""文档生命周期：上传、内联降级、pgvector 同步、重建与删除。"""

from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from ..models import ApprovalRequest, Document, DocumentChunk, DocumentIngestionJob, EmbeddingRecord, KnowledgeBase
from ..services.ingestion_jobs import dispatch_ingestion_job
from ..services.rag import LOCAL_EMBEDDING_DIMENSIONS, LOCAL_EMBEDDING_MODEL
from ..services.vector_store import vector_literal
from .support import NO_MODEL_ENV, TEST_MEDIA_ROOT, AdminApiTestCase, post_and_run_commit_callbacks


class DocumentLifecycleTests(AdminApiTestCase):

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

        response = post_and_run_commit_callbacks(
            self,
            "/api/agent/documents/",
            {"file": upload, "title": "RAG Notes"},
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertIn("task_id", payload)
        self.assertEqual(payload["ingestion_job"]["status"], "pending")
        self.assertTrue(payload["task_url"].endswith(payload["task_id"] + "/"))
        self.assertEqual(payload["desired_ingestion_generation"], 1)
        self.assertEqual(payload["active_ingestion_generation"], 0)
        self.assertEqual(payload["ingestion_error_code"], "")
        document = Document.objects.get(pk=payload["id"])
        job = DocumentIngestionJob.objects.get(pk=payload["task_id"])
        self.assertEqual(document.status, Document.Status.READY)
        self.assertEqual(job.status, DocumentIngestionJob.Status.COMPLETED)
        self.assertGreaterEqual(document.chunk_count, 1)
        self.assertEqual(document.desired_ingestion_generation, 1)
        self.assertEqual(document.active_ingestion_generation, 1)
        self.assertEqual(KnowledgeBase.objects.count(), 1)
        self.assertEqual(DocumentChunk.objects.count(), document.chunk_count)
        self.assertEqual(EmbeddingRecord.objects.count(), document.chunk_count)

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CELERY_TASK_ALWAYS_EAGER=False, DEBUG=False)
    @patch.dict("os.environ", NO_MODEL_ENV)
    @patch("apps.agent_api.tasks.ingest_document_task.apply_async", side_effect=ConnectionError("broker down"))
    def test_document_upload_is_durable_and_dispatcher_recovers_after_broker_failure(self, _apply_async):
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
        self.assertEqual(payload["task_url"], f"/api/agent/tasks/{payload['task_id']}/")
        document = Document.objects.get(pk=payload["id"])
        job = DocumentIngestionJob.objects.get(pk=payload["task_id"])
        self.assertTrue(document.source_file.storage.exists(document.source_file.name))
        with document.source_file.open("rb") as saved_file:
            self.assertEqual(saved_file.read(), b"Local development upload should work without a broker.")
        dispatch_ingestion_job(str(job.pk))
        job.refresh_from_db()
        self.assertEqual(job.status, DocumentIngestionJob.Status.RETRY)
        self.assertEqual(job.failure_code, "broker_unavailable")
        self.assertEqual(document.status, Document.Status.PENDING)

        job.next_attempt_at = timezone.now()
        job.save(update_fields=["next_attempt_at", "updated_at"])
        _apply_async.side_effect = None
        _apply_async.return_value = None
        self.assertTrue(dispatch_ingestion_job(str(job.pk)))
        job.refresh_from_db()
        self.assertEqual(job.status, DocumentIngestionJob.Status.QUEUED)

        document.delete()
        missing = self.client.get(f"/api/agent/tasks/{job.pk}/", HTTP_HOST="localhost")
        self.assertEqual(missing.status_code, 404)

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

        response = post_and_run_commit_callbacks(
            self,
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
        self.assertEqual(record.status, EmbeddingRecord.Status.READY)
        self.assertEqual(record.provider, "local")
        self.assertEqual(record.model_version, "sha256-token-hash-v1")
        self.assertEqual(record.algorithm_version, "sha256-token-hash-v1")

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
        upload_response = post_and_run_commit_callbacks(
            self,
            "/api/agent/documents/",
            {"file": upload, "title": "Reindex"},
            HTTP_HOST="localhost",
        )
        document_id = upload_response.json()["id"]

        response = post_and_run_commit_callbacks(
            self,
            f"/api/agent/documents/{document_id}/reindex/",
            {},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertIn("task_id", payload)
        self.assertEqual(payload["desired_ingestion_generation"], 2)
        self.assertEqual(payload["active_ingestion_generation"], 1)
        self.assertEqual(payload["ingestion_error_code"], "")
        document = Document.objects.get(pk=document_id)
        self.assertEqual(document.desired_ingestion_generation, 2)
        self.assertEqual(document.active_ingestion_generation, 2)
        self.assertEqual(document.status, Document.Status.READY)
        self.assertGreaterEqual(document.chunk_count, 1)

    def test_knowledge_base_list_and_patch_and_legacy_document_serialization(self):
        knowledge_base = KnowledgeBase.objects.create(name="serialization-contract")
        legacy_document = Document.objects.create(
            knowledge_base=knowledge_base,
            title="Legacy generation zero",
            status=Document.Status.READY,
            chunk_count=1,
        )
        DocumentChunk.objects.create(
            document=legacy_document,
            knowledge_base=knowledge_base,
            chunk_index=0,
            content="legacy chunks default to generation zero",
        )

        list_response = self.client.get("/api/agent/knowledge-bases/", HTTP_HOST="localhost")
        self.assertEqual(list_response.status_code, 200)
        base_payload = next(item for item in list_response.json() if item["id"] == knowledge_base.id)
        self.assertEqual(base_payload["document_count"], 1)
        self.assertEqual(base_payload["chunk_count"], 1)
        self.assertNotIn("desired_ingestion_generation", base_payload)
        self.assertNotIn("active_ingestion_generation", base_payload)
        self.assertNotIn("ingestion_error_code", base_payload)

        detail_response = self.client.patch(
            f"/api/agent/knowledge-bases/{knowledge_base.id}/",
            {"description": "updated through the detail endpoint"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["description"], "updated through the detail endpoint")
        self.assertNotIn("desired_ingestion_generation", detail_response.json())

        document_response = self.client.get(
            f"/api/agent/documents/?knowledge_base_id={knowledge_base.id}", HTTP_HOST="localhost"
        )
        self.assertEqual(document_response.status_code, 200)
        document_payload = document_response.json()[0]
        self.assertEqual(document_payload["id"], legacy_document.id)
        self.assertEqual(document_payload["desired_ingestion_generation"], 0)
        self.assertEqual(document_payload["active_ingestion_generation"], 0)
        self.assertEqual(document_payload["ingestion_error_code"], "")

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
