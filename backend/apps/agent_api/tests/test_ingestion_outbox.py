"""Failure and generation-switch coverage for the document-ingestion outbox."""

from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.db.models import F
from django.test import TransactionTestCase
from django.utils import timezone

from ..models import Document, DocumentChunk, DocumentIngestionJob, EmbeddingRecord, KnowledgeBase
from ..services.embedding_space import embedding_space_identity
from ..services.ingestion_jobs import dispatch_ingestion_job, process_ingestion_job, schedule_document_ingestion
from ..services.rag.search import search_knowledge_base
from ..services.rag.text import local_embedding
from .support import NO_MODEL_ENV


class DocumentIngestionOutboxTests(TransactionTestCase):
    reset_sequences = True

    def make_document(self, *, workspace="outbox-workspace", title="Outbox source", content="original version"):
        base = KnowledgeBase.objects.create(name=f"base-{workspace}", workspace_key=workspace)
        return Document.objects.create(
            knowledge_base=base,
            workspace_key=workspace,
            title=title,
            content_text=content,
            status=Document.Status.READY,
            chunk_count=1,
        )

    def add_active_legacy_chunk(self, document, text="original version"):
        chunk = DocumentChunk.objects.create(
            document=document,
            knowledge_base=document.knowledge_base,
            chunk_index=0,
            content=text,
        )
        identity = embedding_space_identity(384, mode="local_hash")
        EmbeddingRecord.objects.create(
            chunk=chunk,
            vector=local_embedding(text),
            status=EmbeddingRecord.Status.READY,
            **identity.as_record_fields(),
        )
        return chunk

    def test_outbox_callback_runs_only_after_job_and_source_commit(self):
        document = self.make_document()
        observed = []

        def dispatch(job_id):
            observed.append(
                DocumentIngestionJob.objects.filter(pk=job_id, document__content_text="original version").exists()
            )

        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job", side_effect=dispatch):
            with self.subTest("job is committed before dispatch"):
                job = schedule_document_ingestion(document)
        self.assertEqual(observed, [True])
        self.assertEqual(job.status, DocumentIngestionJob.Status.PENDING)

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_new_generation_switch_is_atomic_and_duplicate_delivery_is_idempotent(self):
        document = self.make_document()
        old_chunk = self.add_active_legacy_chunk(document)
        document.content_text = "replacement generation contains a new fact"
        document.save(update_fields=["content_text", "updated_at"])
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            job = schedule_document_ingestion(document)

        from ..services.rag.ingest import build_document_index as build, persist_document_index as persist

        def inspect_build(snapshot):
            self.assertFalse(
                connection.in_atomic_block, "document parsing and embedding must be outside DB transactions"
            )
            return build(snapshot)

        def inspect_then_persist(*args, **kwargs):
            document.refresh_from_db()
            self.assertEqual(document.active_ingestion_generation, 0)
            self.assertTrue(DocumentChunk.objects.filter(pk=old_chunk.pk).exists())
            return persist(*args, **kwargs)

        with patch("apps.agent_api.services.rag.ingest.build_document_index", side_effect=inspect_build):
            with patch("apps.agent_api.services.rag.ingest.persist_document_index", side_effect=inspect_then_persist):
                result = process_ingestion_job(str(job.pk))
        self.assertEqual(result["status"], Document.Status.READY)
        document.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(document.active_ingestion_generation, job.generation)
        self.assertEqual(job.status, DocumentIngestionJob.Status.COMPLETED)
        self.assertFalse(DocumentChunk.objects.filter(pk=old_chunk.pk).exists())
        active_chunks = list(document.chunks.filter(ingestion_generation=document.active_ingestion_generation))
        self.assertTrue(active_chunks)
        self.assertIn("replacement generation", " ".join(chunk.content for chunk in active_chunks))

        repeated = process_ingestion_job(str(job.pk))
        self.assertTrue(repeated["idempotent"])
        self.assertEqual(document.chunks.count(), len(active_chunks))

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_stale_generation_cannot_overwrite_latest_and_workspace_isolation_remains(self):
        document = self.make_document(workspace="workspace-a")
        document.status = Document.Status.PENDING
        document.save(update_fields=["status", "updated_at"])
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            old_job = schedule_document_ingestion(document)
            document.content_text = "latest workspace-a indexed phrase"
            document.save(update_fields=["content_text", "updated_at"])
            new_job = schedule_document_ingestion(document)

        stale = process_ingestion_job(str(old_job.pk))
        self.assertEqual(stale["status"], DocumentIngestionJob.Status.SUPERSEDED)
        process_ingestion_job(str(new_job.pk))

        other = self.make_document(
            workspace="workspace-b", title="Other workspace", content="latest workspace-b secret"
        )
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            other_job = schedule_document_ingestion(other)
        process_ingestion_job(str(other_job.pk))

        self.assertEqual(
            list(DocumentChunk.objects.filter(document=document).values_list("content", flat=True)),
            ["latest workspace-a indexed phrase"],
        )
        results = search_knowledge_base("latest workspace-b secret", workspace_key="workspace-a", limit=5)
        self.assertTrue(all(item.document_id == document.pk for item in results))
        self.assertNotIn(other.pk, {item.document_id for item in results})

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_failed_reindex_keeps_last_good_generation_searchable_and_exposes_failure_code(self):
        document = self.make_document()
        previous = self.add_active_legacy_chunk(document)
        document.content_text = "a new generation that cannot be embedded"
        document.save(update_fields=["content_text", "updated_at"])
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            job = schedule_document_ingestion(document, force=True)

        from ..services.embedding_space import EmbeddingSpaceError

        with patch(
            "apps.agent_api.services.rag.ingest.build_document_index",
            side_effect=EmbeddingSpaceError("provider timeout"),
        ):
            process_ingestion_job(str(job.pk))
        document.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(document.status, Document.Status.READY)
        self.assertEqual(document.ingestion_error_code, "embedding_space_invalid")
        self.assertEqual(job.status, DocumentIngestionJob.Status.RETRY)
        self.assertEqual(job.failure_code, "embedding_space_invalid")
        results = search_knowledge_base("original version", workspace_key=document.workspace_key, limit=5)
        self.assertIn(previous.pk, {item.chunk_id for item in results})

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_worker_that_loses_lease_cannot_commit_after_new_attempt_takes_over(self):
        document = self.make_document(content="generation with an in-flight stale worker")
        document.status = Document.Status.PENDING
        document.save(update_fields=["status", "updated_at"])
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            job = schedule_document_ingestion(document)
        job.status = DocumentIngestionJob.Status.QUEUED
        job.attempts = 1
        job.save(update_fields=["status", "attempts", "updated_at"])

        from ..services.rag.ingest import build_document_index as build

        def build_then_lose_lease(snapshot):
            result = build(snapshot)
            DocumentIngestionJob.objects.filter(pk=job.pk).update(
                status=DocumentIngestionJob.Status.QUEUED,
                attempts=F("attempts") + 1,
            )
            return result

        with patch("apps.agent_api.services.rag.ingest.build_document_index", side_effect=build_then_lose_lease):
            result = process_ingestion_job(str(job.pk))

        job.refresh_from_db()
        document.refresh_from_db()
        self.assertTrue(result["stale_attempt"])
        self.assertEqual(job.status, DocumentIngestionJob.Status.QUEUED)
        self.assertEqual(document.active_ingestion_generation, 0)
        self.assertFalse(document.chunks.exists())
        job.lease_expires_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["lease_expires_at", "updated_at"])
        with patch("apps.agent_api.tasks.ingest_document_task.apply_async", return_value=None):
            self.assertTrue(dispatch_ingestion_job(str(job.pk)))
        job.refresh_from_db()
        self.assertEqual(job.status, DocumentIngestionJob.Status.QUEUED)
        self.assertEqual(job.attempts, 3)

    def test_broker_failures_are_bounded_and_become_visible_dead_letter(self):
        document = Document.objects.create(
            knowledge_base=KnowledgeBase.objects.create(name="dead-letter", workspace_key="dead-letter"),
            workspace_key="dead-letter",
            title="no active index",
            content_text="cannot dispatch",
        )
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            job = schedule_document_ingestion(document)
        with patch(
            "apps.agent_api.tasks.ingest_document_task.apply_async", side_effect=ConnectionError("broker unavailable")
        ):
            for _ in range(5):
                job.refresh_from_db()
                if job.status == DocumentIngestionJob.Status.RETRY:
                    job.next_attempt_at = timezone.now()
                    job.save(update_fields=["next_attempt_at", "updated_at"])
                dispatch_ingestion_job(str(job.pk))

        job.refresh_from_db()
        document.refresh_from_db()
        self.assertEqual(job.attempts, job.max_attempts, f"status={job.status}, failure={job.failure_code}")
        self.assertEqual(job.status, DocumentIngestionJob.Status.FAILED)
        self.assertEqual(job.failure_code, "broker_unavailable")
        self.assertEqual(document.status, Document.Status.FAILED)
        self.assertEqual(document.ingestion_error_code, "broker_unavailable")
