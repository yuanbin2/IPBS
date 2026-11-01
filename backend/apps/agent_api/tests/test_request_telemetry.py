"""Isolated request/run/task correlation and terminal alert verification."""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from agent.agent_types import MultiAgentResponse, SupervisorDecision
from agent.model_accounting import model_purpose
from agent.telemetry import correlate, emit, stage_summary, timed_stage

from ..models import AgentRun, Document, DocumentIngestionJob, KnowledgeBase
from ..services.ingestion_jobs import process_ingestion_job, schedule_document_ingestion
from .support import OperatorApiTestCase


class RequestCorrelationTests(OperatorApiTestCase):
    def test_upload_and_chat_keep_request_task_run_and_stage_links(self):
        upload = SimpleUploadedFile("private.txt", b"PRIVATE_BODY for timing", content_type="text/plain")
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            response = self.client.post(
                "/api/agent/documents/", {"file": upload}, HTTP_HOST="localhost", HTTP_X_REQUEST_ID="sk-private"
            )
        self.assertEqual(response.status_code, 202)
        upload_id = response["X-Request-ID"]
        task_id = response.json()["task_id"]
        job = DocumentIngestionJob.objects.get(pk=task_id)
        self.assertEqual(job.request_id, upload_id)
        self.assertNotEqual(upload_id, "sk-private")
        self.assertEqual(response.json()["request_id"], upload_id)
        status = self.client.get(f"/api/agent/tasks/{task_id}/", HTTP_HOST="localhost")
        self.assertEqual(status.json()["request_id"], upload_id)
        self.assertEqual(status.json()["attempts"], 0)

        run_id = uuid.uuid4()

        def answer(*_args, **_kwargs):
            with timed_stage("retrieval"):
                pass
            with model_purpose("rag_answer"):
                FakeListChatModel(responses=["answer"]).invoke("PRIVATE_BODY")
            return MultiAgentResponse(
                answer="answer",
                tool_calls=[],
                sources=[],
                trace=[],
                route="retrieve",
                token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                supervisor=SupervisorDecision("rag_agent", "RAG", "mock", 1.0, "mock"),
            )

        with patch("apps.agent_api.views.chat.MultiAgentSupervisor.chat", side_effect=answer):
            chat = self.client.post(
                "/api/agent/chat/",
                {"message": "test", "run_id": str(run_id)},
                content_type="application/json",
                HTTP_HOST="localhost",
            )
        self.assertEqual(chat.status_code, 200)
        chat_request_id = chat["X-Request-ID"]
        run = AgentRun.objects.get(run_id=run_id)
        self.assertEqual(run.request_id, chat_request_id)
        self.assertEqual(run.model_calls[0]["request_id"], chat_request_id)
        self.assertEqual(run.model_calls[0]["run_id"], str(run_id))
        self.assertEqual(run.stage_timings["retrieval_calls"], 1)
        self.assertEqual(run.stage_timings["model_calls"], 1)
        self.assertGreaterEqual(run.stage_timings["queue_wait_ms"], 0)
        self.assertEqual(chat.json()["request_id"], chat_request_id)
        self.assertNotEqual(upload_id, chat_request_id)
        detail = self.client.get(f"/api/agent/chat/runs/{run_id}/", HTTP_HOST="localhost")
        self.assertEqual(detail.json()["request_id"], chat_request_id)
        with self.assertLogs("agent.telemetry", level="INFO") as captured:
            retry = self.client.post(
                "/api/agent/chat/",
                {"message": "test", "run_id": str(run_id)},
                content_type="application/json",
                HTTP_HOST="localhost",
            )
        self.assertEqual(retry.status_code, 200)
        self.assertNotEqual(retry["X-Request-ID"], chat_request_id)
        self.assertEqual(AgentRun.objects.filter(run_id=run_id).count(), 1)
        reused = [line for line in captured.output if '"event": "run_reused"' in line]
        self.assertEqual(len(reused), 1)
        self.assertIn(retry["X-Request-ID"], reused[0])
        self.assertIn(str(run_id), reused[0])

    def test_task_status_does_not_expose_another_workspace_job(self):
        base = KnowledgeBase.objects.create(name="other", workspace_key="another-workspace")
        document = Document.objects.create(knowledge_base=base, workspace_key="another-workspace", title="private")
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            job = schedule_document_ingestion(document)
        response = self.client.get(f"/api/agent/tasks/{job.pk}/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 404)

    @override_settings(
        AGENT_ALERT_EMAILS=["alerts@example.invalid"],
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_chat_terminal_failure_sends_sanitized_alert_in_memory(self):
        with self.captureOnCommitCallbacks(execute=True):
            with patch(
                "apps.agent_api.views.chat.MultiAgentSupervisor.chat",
                side_effect=TimeoutError("PRIVATE_BODY sk-secret"),
            ):
                response = self.client.post(
                    "/api/agent/chat/",
                    {"message": "PRIVATE_BODY", "run_id": str(uuid.uuid4())},
                    content_type="application/json",
                    HTTP_HOST="localhost",
                )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn("chat_run_failed", body)
        self.assertIn(response["X-Request-ID"], body)
        self.assertNotIn("PRIVATE_BODY", body)
        self.assertNotIn("sk-secret", body)


class IngestionAlertTests(TransactionTestCase):
    def test_embedding_stage_is_linked_to_upload_task(self):
        base = KnowledgeBase.objects.create(name="isolated", workspace_key="timing-test")
        document = Document.objects.create(
            knowledge_base=base, workspace_key="timing-test", title="private", content_text="PRIVATE_BODY for indexing"
        )
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            job = schedule_document_ingestion(document)
        job.status = DocumentIngestionJob.Status.QUEUED
        job.attempts = 1
        job.lease_expires_at = timezone.now() + timedelta(minutes=10)
        job.save(update_fields=["status", "attempts", "lease_expires_at", "updated_at"])
        with self.assertLogs("agent.telemetry", level="INFO") as captured:
            result = process_ingestion_job(str(job.pk))
        job.refresh_from_db()
        self.assertEqual(result["status"], Document.Status.READY)
        self.assertIn("last_embedding_ms", job.timings)
        embedding_events = [line for line in captured.output if '"stage": "embedding"' in line]
        self.assertTrue(embedding_events)
        self.assertIn(job.request_id, embedding_events[0])
        self.assertIn(str(job.pk), embedding_events[0])
        self.assertNotIn("PRIVATE_BODY", "\n".join(captured.output))

    @override_settings(
        AGENT_ALERT_EMAILS=["alerts@example.invalid"],
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_terminal_ingestion_failure_alert_has_ids_and_no_content(self):
        base = KnowledgeBase.objects.create(name="isolated", workspace_key="alert-test")
        document = Document.objects.create(
            knowledge_base=base, workspace_key="alert-test", title="private", content_text="PRIVATE_BODY"
        )
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            job = schedule_document_ingestion(document)
        job.max_attempts = 1
        job.attempts = 1
        job.status = DocumentIngestionJob.Status.QUEUED
        job.lease_expires_at = timezone.now() + timedelta(minutes=10)
        job.save(update_fields=["max_attempts", "attempts", "status", "lease_expires_at"])
        with patch(
            "apps.agent_api.services.rag.ingest.build_document_index",
            side_effect=RuntimeError("PRIVATE_BODY sk-secret"),
        ):
            process_ingestion_job(str(job.pk))
        job.refresh_from_db()
        self.assertEqual(job.status, DocumentIngestionJob.Status.FAILED)
        self.assertEqual(job.failure_code, "document_ingestion_failed")
        self.assertGreaterEqual(job.timings["queue_wait_ms"], 0)
        self.assertGreaterEqual(job.timings["last_processing_ms"], 0)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn(str(job.pk), body)
        self.assertIn(job.request_id, body)
        self.assertNotIn("PRIVATE_BODY", body)
        self.assertNotIn("sk-secret", body)


class TelemetrySafetyTests(SimpleTestCase):
    def test_measured_stage_classification_and_log_allowlist(self):
        summary = stage_summary(
            [{"stage": "retrieval", "duration_ms": 30}],
            [{"latency_ms": 90}],
            queue_wait_ms=10,
            total_ms=145,
        )
        self.assertEqual(summary["largest_measured_stage"], "model")
        self.assertEqual(summary["retrieval_ms"], 30)
        self.assertEqual(summary["model_ms"], 90)
        with self.assertLogs("agent.telemetry", level="INFO") as captured:
            with correlate(request_id="00000000-0000-4000-8000-000000000001"):
                emit(
                    "stage_completed",
                    stage="retrieval",
                    duration_ms=30,
                    prompt="PRIVATE_BODY",
                    error_code="PRIVATE_BODY",
                )
        self.assertIn("00000000-0000-4000-8000-000000000001", captured.output[0])
        self.assertNotIn("PRIVATE_BODY", captured.output[0])
        self.assertIn('"error_code": "other_failure"', captured.output[0])
