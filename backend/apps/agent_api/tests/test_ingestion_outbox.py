"""Failure and generation-switch coverage for the document-ingestion outbox."""

from datetime import timedelta
from unittest.mock import patch

from billiard.exceptions import SoftTimeLimitExceeded
from django.db import connection
from django.db.models import F
from django.test import TransactionTestCase
from django.utils import timezone

from ..models import Document, DocumentChunk, DocumentIngestionJob, EmbeddingRecord, KnowledgeBase
from ..services.embedding_space import embedding_space_identity
from ..services.ingestion_jobs import (
    JOB_LEASE,
    dispatch_due_ingestion_jobs,
    dispatch_ingestion_job,
    process_ingestion_job,
    schedule_document_ingestion,
)
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

    def queue_job(self, job):
        job.status = DocumentIngestionJob.Status.QUEUED
        job.attempts = max(job.attempts, 1)
        job.lease_expires_at = timezone.now() + JOB_LEASE
        job.save(update_fields=["status", "attempts", "lease_expires_at", "updated_at"])

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
        self.queue_job(job)

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
        self.queue_job(old_job)
        self.queue_job(new_job)

        stale = process_ingestion_job(str(old_job.pk))
        self.assertEqual(stale["status"], DocumentIngestionJob.Status.SUPERSEDED)
        process_ingestion_job(str(new_job.pk))

        other = self.make_document(
            workspace="workspace-b", title="Other workspace", content="latest workspace-b secret"
        )
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            other_job = schedule_document_ingestion(other)
        self.queue_job(other_job)
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
        self.queue_job(job)

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
        job.lease_expires_at = timezone.now() + JOB_LEASE
        job.save(update_fields=["status", "attempts", "lease_expires_at", "updated_at"])

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
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            replacement = schedule_document_ingestion(document, force=True)
        self.assertEqual(replacement.generation, job.generation + 1)
        self.assertEqual(replacement.status, DocumentIngestionJob.Status.PENDING)
        self.assertEqual(DocumentIngestionJob.objects.get(pk=job.pk).status, DocumentIngestionJob.Status.FAILED)

    def test_late_publish_failure_cannot_overwrite_newer_dispatch_attempt(self):
        document = self.make_document(content="broker race")
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            job = schedule_document_ingestion(document)

        def newer_attempt_then_fail(*_args, **_kwargs):
            DocumentIngestionJob.objects.filter(pk=job.pk).update(attempts=2)
            raise ConnectionError("publish result arrived late")

        with patch("apps.agent_api.tasks.ingest_document_task.apply_async", side_effect=newer_attempt_then_fail):
            self.assertFalse(dispatch_ingestion_job(str(job.pk)))
        job.refresh_from_db()
        self.assertEqual(job.attempts, 2)
        self.assertEqual(job.status, DocumentIngestionJob.Status.QUEUED)
        self.assertEqual(job.failure_code, "")

    def test_redelivered_message_cannot_bypass_outbox_backoff_or_lease(self):
        document = self.make_document(content="backoff is owned by the outbox")
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            job = schedule_document_ingestion(document)
        with patch("apps.agent_api.services.rag.ingest.build_document_index") as build:
            self.assertTrue(process_ingestion_job(str(job.pk))["deferred"])
            self.queue_job(job)
            job.status = DocumentIngestionJob.Status.RETRY
            job.next_attempt_at = timezone.now() + timedelta(minutes=1)
            job.save(update_fields=["status", "next_attempt_at", "updated_at"])
            self.assertTrue(process_ingestion_job(str(job.pk))["deferred"])
            job.status = DocumentIngestionJob.Status.PROCESSING
            job.lease_expires_at = timezone.now() - timedelta(seconds=1)
            job.save(update_fields=["status", "lease_expires_at", "updated_at"])
            self.assertTrue(process_ingestion_job(str(job.pk))["duplicate"])
            job.status = DocumentIngestionJob.Status.QUEUED
            job.save(update_fields=["status", "updated_at"])
            self.assertTrue(process_ingestion_job(str(job.pk))["deferred"])
            build.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.attempts, 1)
        self.assertFalse(document.chunks.exists())

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_old_generation_finishing_after_reindex_cannot_activate_old_chunks(self):
        document = self.make_document(content="old generation")
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            old_job = schedule_document_ingestion(document)
        self.queue_job(old_job)

        from ..services.rag.ingest import build_document_index as build

        def reindex_during_build(snapshot):
            old_index = build(snapshot)
            document.content_text = "new generation"
            document.save(update_fields=["content_text", "updated_at"])
            with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
                self.new_job = schedule_document_ingestion(document, force=True)
            self.queue_job(self.new_job)
            return old_index

        with patch("apps.agent_api.services.rag.ingest.build_document_index", side_effect=reindex_during_build):
            stale = process_ingestion_job(str(old_job.pk))
        self.assertEqual(stale["status"], DocumentIngestionJob.Status.SUPERSEDED)
        self.assertFalse(document.chunks.exists())
        ready = process_ingestion_job(str(self.new_job.pk))
        self.assertEqual(ready["status"], Document.Status.READY)
        document.refresh_from_db()
        self.assertEqual(document.active_ingestion_generation, self.new_job.generation)
        self.assertEqual(list(document.chunks.values_list("content", flat=True)), ["new generation"])

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_deleted_document_cannot_be_reactivated_by_in_flight_worker(self):
        document = self.make_document(content="deleted while embedding")
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            job = schedule_document_ingestion(document)
        self.queue_job(job)
        document_id = document.pk

        def delete_during_build(_snapshot):
            Document.objects.get(pk=document_id).delete()
            return (["obsolete"], [[0.0] * 384], None)

        with patch("apps.agent_api.services.rag.ingest.build_document_index", side_effect=delete_during_build):
            result = process_ingestion_job(str(job.pk))
        self.assertEqual(result["status"], "deleted")
        self.assertFalse(Document.objects.filter(pk=document_id).exists())
        self.assertFalse(DocumentChunk.objects.filter(document_id=document_id).exists())
        self.assertFalse(EmbeddingRecord.objects.filter(chunk__document_id=document_id).exists())
        self.assertEqual(process_ingestion_job(str(job.pk))["status"], "deleted")

    def test_deleted_document_during_failed_build_does_not_retry_or_resurrect(self):
        document = self.make_document(content="deleted before build raises")
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            job = schedule_document_ingestion(document)
        self.queue_job(job)
        document_id = document.pk

        def delete_then_fail(_snapshot):
            Document.objects.get(pk=document_id).delete()
            raise RuntimeError("source file disappeared")

        with patch("apps.agent_api.services.rag.ingest.build_document_index", side_effect=delete_then_fail):
            result = process_ingestion_job(str(job.pk))
        self.assertEqual(result["status"], "deleted")
        self.assertFalse(Document.objects.filter(pk=document_id).exists())
        self.assertFalse(DocumentIngestionJob.objects.filter(pk=job.pk).exists())
        self.assertFalse(DocumentChunk.objects.filter(document_id=document_id).exists())

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_soft_timeout_retries_and_worker_loss_is_recovered_after_lease(self):
        from ..tasks import ingest_document_task

        self.assertLess(ingest_document_task.soft_time_limit, ingest_document_task.time_limit)
        self.assertLess(ingest_document_task.time_limit, JOB_LEASE.total_seconds())
        document = self.make_document(content="retry after timeout")
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            job = schedule_document_ingestion(document)
        job.status = DocumentIngestionJob.Status.QUEUED
        job.attempts = 1
        job.lease_expires_at = timezone.now() + JOB_LEASE
        job.save(update_fields=["status", "attempts", "lease_expires_at", "updated_at"])
        with patch("apps.agent_api.services.rag.ingest.build_document_index", side_effect=SoftTimeLimitExceeded()):
            result = process_ingestion_job(str(job.pk))
        self.assertEqual(result["status"], "retry")
        job.refresh_from_db()
        self.assertEqual(job.status, DocumentIngestionJob.Status.RETRY)
        self.assertEqual(job.failure_code, "ingestion_timeout")
        self.assertFalse(document.chunks.exists())

        # A hard-killed worker cannot update the row; beat reclaims only an expired lease.
        job.status = DocumentIngestionJob.Status.PROCESSING
        job.next_attempt_at = None
        job.lease_expires_at = timezone.now() + timedelta(minutes=1)
        job.save(update_fields=["status", "next_attempt_at", "lease_expires_at", "updated_at"])
        with patch("apps.agent_api.tasks.ingest_document_task.apply_async", return_value=None) as publish:
            self.assertEqual(dispatch_due_ingestion_jobs(), 0)
            publish.assert_not_called()
            job.lease_expires_at = timezone.now() - timedelta(seconds=1)
            job.save(update_fields=["lease_expires_at", "updated_at"])
            self.assertEqual(dispatch_due_ingestion_jobs(), 1)
            publish.assert_called_once()
        job.refresh_from_db()
        self.assertEqual(job.status, DocumentIngestionJob.Status.QUEUED)
        self.assertEqual(job.attempts, 2)
