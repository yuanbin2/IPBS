"""Transactional outbox and versioned document-index activation."""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timedelta

from billiard.exceptions import SoftTimeLimitExceeded
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from agent.telemetry import collect_stages, correlate, current_request_id, emit, failure_alert, safe_error_code

from ..models import Document, DocumentIngestionJob

logger = logging.getLogger(__name__)
JOB_LEASE = timedelta(minutes=10)
MAX_DISPATCH_BACKOFF = 15 * 60


def document_file_digest(document: Document) -> str:
    digest = hashlib.sha256()
    if document.source_file and document.source_file.name:
        with default_storage.open(document.source_file.name, "rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def uploaded_file_digest(upload) -> str:
    digest = hashlib.sha256()
    for block in upload.chunks():
        digest.update(block)
    upload.seek(0)
    return digest.hexdigest()


def _content_version(document: Document, file_sha256: str | None = None) -> str:
    if file_sha256 is None:
        file_sha256 = document_file_digest(document) if not document.content_text.strip() else ""
    snapshot = {
        "title": document.title,
        "content_text": document.content_text,
        "content_type": document.content_type,
        "workspace_key": document.workspace_key,
        "knowledge_base_id": document.knowledge_base_id,
        "file_sha256": file_sha256,
    }
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def schedule_document_ingestion(
    document: Document, *, force: bool = False, source_digest: str | None = None
) -> DocumentIngestionJob:
    """Persist a generation before registering its post-commit broker dispatch."""
    document.refresh_from_db()
    version = _content_version(document, source_digest)  # Storage I/O stays outside the row-lock transaction.
    snapshot_fields = (
        document.title,
        document.content_text,
        document.content_type,
        document.source_file.name if document.source_file else "",
        document.workspace_key,
        document.knowledge_base_id,
    )
    with transaction.atomic():
        locked = Document.objects.select_for_update().get(pk=document.pk)
        locked_fields = (
            locked.title,
            locked.content_text,
            locked.content_type,
            locked.source_file.name if locked.source_file else "",
            locked.workspace_key,
            locked.knowledge_base_id,
        )
        if locked_fields != snapshot_fields:
            raise RuntimeError("document_changed_while_scheduling")
        if not force:
            existing = (
                locked.ingestion_jobs.filter(content_version=version)
                .exclude(status__in=[DocumentIngestionJob.Status.FAILED, DocumentIngestionJob.Status.SUPERSEDED])
                .order_by("-generation")
                .first()
            )
            if existing and existing.generation == locked.desired_ingestion_generation:
                if existing.status in {DocumentIngestionJob.Status.PENDING, DocumentIngestionJob.Status.RETRY}:
                    transaction.on_commit(lambda job_id=str(existing.pk): dispatch_ingestion_job(job_id))
                return existing

        generation = locked.desired_ingestion_generation + 1
        key = f"document:{locked.pk}:generation:{generation}:version:{version}"
        job = DocumentIngestionJob.objects.create(
            document=locked,
            request_id=current_request_id() or str(uuid.uuid4()),
            generation=generation,
            content_version=version,
            idempotency_key=key,
            title_snapshot=locked.title,
            content_text_snapshot=locked.content_text,
            content_type_snapshot=locked.content_type,
            source_file_name=locked.source_file.name if locked.source_file else "",
            workspace_key=locked.workspace_key,
            knowledge_base_id=locked.knowledge_base_id,
        )
        locked.desired_ingestion_generation = generation
        locked.ingestion_error_code = ""
        has_active_index = locked.chunks.filter(ingestion_generation=locked.active_ingestion_generation).exists()
        if not has_active_index:
            locked.status = Document.Status.PENDING
        locked.save(update_fields=["desired_ingestion_generation", "ingestion_error_code", "status", "updated_at"])
        transaction.on_commit(lambda job_id=str(job.pk): dispatch_ingestion_job(job_id))
        with correlate(request_id=job.request_id, task_id=job.pk):
            emit("ingestion_scheduled", status=job.status, document_id=locked.pk)
        return job


def _retry(
    job_id: str,
    code: str,
    *,
    expected_status: str | None = None,
    expected_attempts: int | None = None,
    processing_ms: int | None = None,
    embedding_ms: int | None = None,
) -> None:
    now = timezone.now()
    terminal = False
    with transaction.atomic():
        job = DocumentIngestionJob.objects.select_for_update().filter(pk=job_id).first()
        if job is None:  # The document and its jobs were deleted while a worker was building.
            return
        if job.status in {
            DocumentIngestionJob.Status.COMPLETED,
            DocumentIngestionJob.Status.FAILED,
            DocumentIngestionJob.Status.SUPERSEDED,
        }:
            return
        if expected_status is not None and job.status != expected_status:
            return
        if expected_attempts is not None and job.attempts != expected_attempts:
            return
        job.failure_code = code[:100]
        job.failure_message = "Indexing could not be completed; retry or rebuild the document index."
        job.lease_expires_at = None
        document = Document.objects.select_for_update().get(pk=job.document_id)
        if document.desired_ingestion_generation == job.generation:
            has_active_index = document.chunks.filter(
                ingestion_generation=document.active_ingestion_generation
            ).exists()
            updates = {"ingestion_error_code": job.failure_code}
            if not has_active_index:
                updates["status"] = Document.Status.FAILED
            Document.objects.filter(pk=job.document_id).update(**updates)
        if job.attempts >= job.max_attempts:
            job.status = DocumentIngestionJob.Status.FAILED
            job.finished_at = now
            terminal = True
        else:
            job.status = DocumentIngestionJob.Status.RETRY
            delay = min(30 * (2 ** max(job.attempts - 1, 0)), MAX_DISPATCH_BACKOFF)
            job.next_attempt_at = now + timedelta(seconds=delay)
        job.save(
            update_fields=[
                "status",
                "attempts",
                "failure_code",
                "failure_message",
                "lease_expires_at",
                "finished_at",
                "next_attempt_at",
                "updated_at",
            ]
        )
        if processing_ms is not None:
            metrics = dict(job.timings)
            metrics["last_processing_ms"] = processing_ms
            metrics["total_processing_ms"] = metrics.get("total_processing_ms", 0) + processing_ms
            if embedding_ms is not None:
                metrics["last_embedding_ms"] = embedding_ms
                metrics["total_embedding_ms"] = metrics.get("total_embedding_ms", 0) + embedding_ms
            job.timings = metrics
            job.save(update_fields=["timings", "updated_at"])
    with correlate(request_id=job.request_id, task_id=job_id):
        emit(
            "ingestion_retry" if not terminal else "ingestion_terminal_failure",
            status=job.status,
            error_code=code,
            attempt=job.attempts,
        )
    if terminal:
        transaction.on_commit(
            lambda: failure_alert("ingestion_failed", code, request_id=job.request_id, task_id=job_id)
        )


def dispatch_ingestion_job(job_id: str) -> bool:
    """Lease a durable outbox row, then publish outside the DB transaction."""
    now = timezone.now()
    with transaction.atomic():
        job = DocumentIngestionJob.objects.select_for_update().filter(pk=job_id).first()
        if not job or job.status in {
            DocumentIngestionJob.Status.COMPLETED,
            DocumentIngestionJob.Status.FAILED,
            DocumentIngestionJob.Status.SUPERSEDED,
        }:
            return False
        if job.status == DocumentIngestionJob.Status.QUEUED and job.lease_expires_at and job.lease_expires_at > now:
            return False
        if job.status == DocumentIngestionJob.Status.PROCESSING and job.lease_expires_at and job.lease_expires_at > now:
            return False
        if job.status == DocumentIngestionJob.Status.RETRY and job.next_attempt_at and job.next_attempt_at > now:
            return False
        if job.attempts >= job.max_attempts:
            job.status = DocumentIngestionJob.Status.FAILED
            job.failure_code = job.failure_code or "retry_limit_exceeded"
            job.failure_message = "The indexing retry limit was reached; rebuild the document index to retry."
            job.lease_expires_at = None
            job.finished_at = now
            job.save(
                update_fields=[
                    "status",
                    "failure_code",
                    "failure_message",
                    "lease_expires_at",
                    "finished_at",
                    "updated_at",
                ]
            )
            document = Document.objects.get(pk=job.document_id)
            if document.desired_ingestion_generation == job.generation:
                has_active_index = document.chunks.filter(
                    ingestion_generation=document.active_ingestion_generation
                ).exists()
                updates = {"ingestion_error_code": job.failure_code}
                if not has_active_index:
                    updates["status"] = Document.Status.FAILED
                Document.objects.filter(pk=job.document_id).update(**updates)
            transaction.on_commit(
                lambda rid=job.request_id, code=job.failure_code: failure_alert(
                    "ingestion_failed", code, request_id=rid, task_id=job_id
                )
            )
            return False
        job.attempts += 1
        dispatched_attempt = job.attempts
        job.status = DocumentIngestionJob.Status.QUEUED
        metrics = dict(job.timings)
        metrics["queued_at"] = now.isoformat()
        job.timings = metrics
        job.lease_expires_at = now + JOB_LEASE
        job.save(update_fields=["status", "attempts", "timings", "lease_expires_at", "updated_at"])

    dispatched_at = time.perf_counter()
    try:
        from ..tasks import ingest_document_task

        # The database outbox owns retries; avoid Celery's synchronous publish retry in the HTTP callback.
        ingest_document_task.apply_async(args=(str(job_id),), task_id=str(job_id), retry=False)
        with correlate(request_id=job.request_id, task_id=job_id):
            emit(
                "ingestion_dispatched",
                status="queued",
                attempt=dispatched_attempt,
                duration_ms=round((time.perf_counter() - dispatched_at) * 1000),
            )
        return True
    except Exception as exc:  # broker failures must leave a durable retryable row
        logger.warning("document_ingestion_dispatch_failed job_id=%s error_class=%s", job_id, type(exc).__name__)
        with correlate(request_id=job.request_id, task_id=job_id):
            emit(
                "ingestion_dispatch_failed",
                status="retry",
                error_code=type(exc).__name__,
                attempt=dispatched_attempt,
                duration_ms=round((time.perf_counter() - dispatched_at) * 1000),
            )
        _retry(
            job_id,
            "broker_unavailable",
            expected_status=DocumentIngestionJob.Status.QUEUED,
            expected_attempts=dispatched_attempt,
        )
        return False


def dispatch_due_ingestion_jobs(limit: int = 100) -> int:
    """Periodic recovery for unsent, broker-lost, and worker-lost outbox rows."""
    now = timezone.now()
    candidates = (
        DocumentIngestionJob.objects.filter(
            status__in=[
                DocumentIngestionJob.Status.PENDING,
                DocumentIngestionJob.Status.RETRY,
                DocumentIngestionJob.Status.QUEUED,
                DocumentIngestionJob.Status.PROCESSING,
            ]
        )
        .filter(models_q_due(now))
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    )
    count = 0
    for job_id in candidates:
        count += dispatch_ingestion_job(str(job_id))
    return count


def models_q_due(now):
    from django.db.models import Q

    return (
        Q(status=DocumentIngestionJob.Status.PENDING)
        | Q(status=DocumentIngestionJob.Status.RETRY, next_attempt_at__lte=now)
        | Q(
            status__in=[DocumentIngestionJob.Status.QUEUED, DocumentIngestionJob.Status.PROCESSING],
            lease_expires_at__lte=now,
        )
    )


def process_ingestion_job(job_id: str) -> dict:
    """Perform parsing/provider calls without an open DB transaction; atomically switch index last."""
    from .rag.ingest import build_document_index

    now = timezone.now()
    with transaction.atomic():
        job = DocumentIngestionJob.objects.select_for_update().select_related("document").filter(pk=job_id).first()
        if job is None:
            return {"status": "deleted"}
        if job.status in {
            DocumentIngestionJob.Status.COMPLETED,
            DocumentIngestionJob.Status.FAILED,
            DocumentIngestionJob.Status.SUPERSEDED,
        }:
            return {"document_id": job.document_id, "status": job.status, "idempotent": True}
        if job.status == DocumentIngestionJob.Status.PROCESSING:
            return {"document_id": job.document_id, "status": job.status, "duplicate": True}
        if (
            job.status != DocumentIngestionJob.Status.QUEUED
            or job.attempts < 1
            or not job.lease_expires_at
            or job.lease_expires_at <= now
        ):
            return {"document_id": job.document_id, "status": job.status, "deferred": True}
        document = Document.objects.select_for_update().get(pk=job.document_id)
        if job.generation != document.desired_ingestion_generation:
            job.status = DocumentIngestionJob.Status.SUPERSEDED
            job.finished_at = now
            job.save(update_fields=["status", "finished_at", "updated_at"])
            return {"document_id": document.pk, "status": job.status}
        has_active_index = document.chunks.filter(ingestion_generation=document.active_ingestion_generation).exists()
        if not has_active_index:
            document.status = Document.Status.PROCESSING
            document.save(update_fields=["status", "updated_at"])
        job.status = DocumentIngestionJob.Status.PROCESSING
        attempt_number = job.attempts
        metrics = dict(job.timings)
        queued_at = metrics.get("queued_at")
        try:
            queue_origin = datetime.fromisoformat(queued_at) if queued_at else job.created_at
        except ValueError:
            queue_origin = job.created_at
        metrics["queue_wait_ms"] = max(0, round((now - queue_origin).total_seconds() * 1000))
        metrics["processing_started_at"] = now.isoformat()
        job.timings = metrics
        job.lease_expires_at = now + JOB_LEASE
        job.save(update_fields=["status", "timings", "lease_expires_at", "updated_at"])

    processing_started = time.perf_counter()
    build_stages = []
    try:
        document.title = job.title_snapshot
        document.content_text = job.content_text_snapshot
        document.content_type = job.content_type_snapshot
        document.source_file.name = job.source_file_name
        with correlate(request_id=job.request_id, task_id=job_id):
            emit(
                "ingestion_started", status="processing", attempt=attempt_number, queue_wait_ms=metrics["queue_wait_ms"]
            )
            with collect_stages() as build_stages:
                chunks, vectors, identity = build_document_index(document)
        with transaction.atomic():
            job = DocumentIngestionJob.objects.select_for_update().filter(pk=job_id).first()
            if job is None:
                return {"status": "deleted"}
            document = Document.objects.select_for_update().get(pk=job.document_id)
            if job.status != DocumentIngestionJob.Status.PROCESSING or job.attempts != attempt_number:
                return {"document_id": document.pk, "status": job.status, "stale_attempt": True}
            if job.generation != document.desired_ingestion_generation:
                job.status = DocumentIngestionJob.Status.SUPERSEDED
                job.finished_at = timezone.now()
                job.save(update_fields=["status", "finished_at", "updated_at"])
                return {"document_id": document.pk, "status": job.status}
            from .rag.ingest import persist_document_index

            persist_document_index(document, chunks, vectors, identity, generation=job.generation)
            document.active_ingestion_generation = job.generation
            document.status = Document.Status.READY
            document.chunk_count = len(chunks)
            document.ingestion_error_code = ""
            document.error_message = ""
            document.save(
                update_fields=[
                    "active_ingestion_generation",
                    "status",
                    "chunk_count",
                    "ingestion_error_code",
                    "error_message",
                    "updated_at",
                ]
            )
            document.chunks.exclude(ingestion_generation=job.generation).delete()
            job.status = DocumentIngestionJob.Status.COMPLETED
            job.failure_code = ""
            job.failure_message = ""
            job.lease_expires_at = None
            job.finished_at = timezone.now()
            metrics = dict(job.timings)
            processing_ms = round((time.perf_counter() - processing_started) * 1000)
            metrics["last_processing_ms"] = processing_ms
            metrics["total_processing_ms"] = metrics.get("total_processing_ms", 0) + processing_ms
            embedding_ms = sum(item["duration_ms"] for item in build_stages if item["stage"] == "embedding")
            metrics["last_embedding_ms"] = embedding_ms
            metrics["total_embedding_ms"] = metrics.get("total_embedding_ms", 0) + embedding_ms
            job.timings = metrics
            job.save(
                update_fields=[
                    "status",
                    "failure_code",
                    "failure_message",
                    "lease_expires_at",
                    "finished_at",
                    "timings",
                    "updated_at",
                ]
            )
        with correlate(request_id=job.request_id, task_id=job_id):
            emit(
                "ingestion_completed",
                status="completed",
                attempt=attempt_number,
                duration_ms=processing_ms,
                count=len(chunks),
            )
        return {"document_id": document.pk, "status": document.status, "chunk_count": len(chunks)}
    except Exception as exc:
        from .embedding_space import EmbeddingSpaceError

        failure_code = getattr(exc, "failure_code", "")
        if not failure_code:
            failure_code = (
                "ingestion_timeout"
                if isinstance(exc, SoftTimeLimitExceeded)
                else "embedding_space_invalid" if isinstance(exc, EmbeddingSpaceError) else "document_ingestion_failed"
            )
        logger.warning("document_ingestion_failed job_id=%s failure_code=%s", job_id, safe_error_code(failure_code))
        _retry(
            job_id,
            failure_code,
            expected_status=DocumentIngestionJob.Status.PROCESSING,
            expected_attempts=attempt_number,
            processing_ms=round((time.perf_counter() - processing_started) * 1000),
            embedding_ms=sum(item["duration_ms"] for item in build_stages if item["stage"] == "embedding"),
        )
        if not DocumentIngestionJob.objects.filter(pk=job_id).exists():
            return {"document_id": job.document_id, "status": "deleted"}
        return {"document_id": job.document_id, "status": "retry"}
