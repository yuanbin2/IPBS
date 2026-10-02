"""Versioned evaluation batch API and worker integration tests."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from ..models import (
    EvaluationBatch,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationDataset,
    EvaluationRun,
)
from ..services.evaluation import SCORER_VERSION, content_hash, snapshot_case
from ..tasks import run_evaluation_batch_task
from .support import OperatorApiTestCase


class EvaluationBatchApiTests(OperatorApiTestCase):
    def make_case(self, *, question="batch question"):
        return EvaluationCase.objects.create(
            question=question,
            category=EvaluationCase.Category.KNOWLEDGE,
            annotation={
                "schema_version": 1,
                "review_status": "human_reviewed",
                "reviewer": "fixture-reviewer",
                "reviewed_at": "2026-09-30T00:00:00Z",
                "claim_review_complete": True,
                "atomic_facts": [
                    {
                        "id": "fact-1",
                        "answer_patterns": ["项目使用 Django"],
                        "allowed_source_ids": ["chunk-1"],
                        "support_patterns": ["项目使用 Django"],
                        "requires_citation": True,
                    }
                ],
                "should_refuse": False,
            },
        )

    def test_dataset_freeze_and_async_batch_request_are_idempotent(self):
        case = self.make_case()
        created = self.client.post(
            "/api/agent/evaluation-datasets/",
            json.dumps({"version": "review-set-v1", "case_ids": [case.pk]}),
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201, created.content.decode())
        dataset_id = created.json()["id"]
        self.assertEqual(created.json()["human_reviewed_count"], 1)

        frozen = self.client.post(
            f"/api/agent/evaluation-datasets/{dataset_id}/freeze/", "{}", content_type="application/json"
        )
        self.assertEqual(frozen.status_code, 200)
        self.assertEqual(frozen.json()["status"], EvaluationDataset.Status.FROZEN)
        dataset = EvaluationDataset.objects.get(pk=dataset_id)
        original_hash = dataset.manifest_hash
        dataset.snapshot[0]["question"] = "mutated"
        with self.assertRaisesMessage(ValueError, "snapshots are immutable"):
            dataset.save()
        dataset.refresh_from_db()
        self.assertEqual(dataset.manifest_hash, original_hash)

        with patch("apps.agent_api.views.observability._dispatch_evaluation_batch") as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    "/api/agent/evaluation-batches/create/",
                    json.dumps({"dataset_id": dataset_id, "limit": 1}),
                    content_type="application/json",
                    HTTP_IDEMPOTENCY_KEY="batch-request-1",
                )
            self.assertEqual(response.status_code, 202)
            payload = response.json()
            batch_id = payload["id"]
            self.assertEqual(payload["status"], EvaluationBatch.Status.QUEUED)
            self.assertEqual(payload["metadata"]["scorer_version"], SCORER_VERSION)
            self.assertEqual(payload["metadata"]["dataset_hash"], original_hash)
            self.assertEqual(payload["progress_percent"], 0)
            self.assertEqual(payload["case_results"][0]["case_snapshot"]["question"], "batch question")
            dispatch.assert_called_once()

            repeated = self.client.post(
                "/api/agent/evaluation-batches/create/",
                json.dumps({"dataset_id": dataset_id, "limit": 1}),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="batch-request-1",
            )
            self.assertEqual(repeated.status_code, 202)
            self.assertEqual(repeated.json()["id"], batch_id)
        self.assertEqual(EvaluationBatch.objects.count(), 1)

    def test_dataset_must_be_frozen_and_other_workspace_cannot_read_batch(self):
        case = self.make_case()
        snapshot = [snapshot_case(case)]
        dataset = EvaluationDataset.objects.create(
            workspace_key="default",
            version="draft-v1",
            manifest_hash=content_hash(snapshot),
            snapshot=snapshot,
        )
        response = self.client.post(
            "/api/agent/evaluation-batches/create/",
            json.dumps({"dataset_id": dataset.pk, "limit": 1}),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="draft-run",
        )
        self.assertEqual(response.status_code, 409)
        batch = EvaluationBatch.objects.create(
            dataset=dataset,
            workspace_key="other-workspace",
            total_cases=1,
            request_hash="a" * 64,
            idempotency_key="other-run",
        )
        forbidden = self.client.get(f"/api/agent/evaluation-batches/{batch.pk}/")
        self.assertEqual(forbidden.status_code, 404)

    def test_queued_batch_with_broker_error_can_be_redispatched(self):
        case = self.make_case()
        snapshot = [snapshot_case(case)]
        dataset = EvaluationDataset.objects.create(
            workspace_key="default",
            version="dispatch-fixture-v1",
            status=EvaluationDataset.Status.FROZEN,
            manifest_hash=content_hash(snapshot),
            snapshot=snapshot,
        )
        batch = EvaluationBatch.objects.create(
            dataset=dataset,
            workspace_key="default",
            total_cases=1,
            metadata={"dispatch_error": "OperationalError"},
            request_hash="c" * 64,
            idempotency_key="dispatch-fixture",
        )
        EvaluationCaseResult.objects.create(
            batch=batch,
            case_key=case.case_key,
            order=1,
            case_snapshot=snapshot[0],
        )

        with patch("apps.agent_api.views.observability._dispatch_evaluation_batch") as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    f"/api/agent/evaluation-batches/{batch.pk}/retry/",
                    "{}",
                    content_type="application/json",
                )

        self.assertEqual(response.status_code, 202)
        self.assertNotIn("dispatch_error", response.json()["metadata"])
        dispatch.assert_called_once()


class EvaluationBatchWorkerTests(TestCase):
    def test_worker_executes_frozen_snapshot_and_persists_provenance_and_result(self):
        case = EvaluationCase.objects.create(
            question="项目使用什么后端框架？",
            category=EvaluationCase.Category.KNOWLEDGE,
            annotation={
                "schema_version": 1,
                "review_status": "human_reviewed",
                "reviewer": "fixture-reviewer",
                "reviewed_at": "2026-09-30T00:00:00Z",
                "claim_review_complete": True,
                "atomic_facts": [
                    {
                        "id": "fact-1",
                        "answer_patterns": ["项目使用 Django"],
                        "allowed_source_ids": ["chunk-1"],
                        "support_patterns": ["项目使用 Django"],
                        "requires_citation": True,
                    }
                ],
            },
        )
        snapshot = [snapshot_case(case)]
        dataset = EvaluationDataset.objects.create(
            workspace_key="default",
            version="worker-fixture-v1",
            status=EvaluationDataset.Status.FROZEN,
            manifest_hash=content_hash(snapshot),
            snapshot=snapshot,
            frozen_at="2026-09-30T00:00:00Z",
        )
        batch = EvaluationBatch.objects.create(
            dataset=dataset,
            workspace_key="default",
            total_cases=1,
            metadata={"scorer_version": SCORER_VERSION, "dataset_hash": dataset.manifest_hash},
            request_hash="b" * 64,
            idempotency_key="worker-fixture",
        )
        result = EvaluationCaseResult.objects.create(
            batch=batch,
            case_key=case.case_key,
            order=1,
            case_snapshot=snapshot[0],
        )
        response_data = {
            "answer": "项目使用 Django [1]。",
            "sources": [{"chunk_id": "chunk-1", "content": "项目使用 Django"}],
            "tool_calls": [{"ok": True}],
        }
        with patch("agent.multi_agent.MultiAgentSupervisor.chat") as chat:
            chat.return_value = SimpleNamespace(to_dict=lambda: response_data)
            outcome = run_evaluation_batch_task.apply(args=(batch.pk,), task_id="eval-test-task").get()

        self.assertEqual(outcome["status"], EvaluationBatch.Status.COMPLETED)
        result.refresh_from_db()
        batch.refresh_from_db()
        self.assertEqual(result.status, EvaluationCaseResult.Status.COMPLETED)
        self.assertTrue(result.passed)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.evaluation_run.metrics["scorer_version"], SCORER_VERSION)
        self.assertEqual(result.evaluation_run.metrics["citation_accuracy"]["score"], 1.0)
        self.assertEqual(EvaluationRun.objects.count(), 1)
        self.assertEqual(batch.status, EvaluationBatch.Status.COMPLETED)
        self.assertIsNotNone(batch.started_at)
        self.assertIsNotNone(batch.finished_at)
        chat.assert_called_once()

        redelivery = run_evaluation_batch_task.apply(args=(batch.pk,), task_id="eval-test-task").get()
        self.assertEqual(redelivery["skipped"], "terminal")
        self.assertEqual(EvaluationRun.objects.count(), 1)
        chat.assert_called_once()
