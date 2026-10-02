"""Celery 后台任务：把耗时的文档解析和向量化移出 HTTP 请求。"""

from pathlib import Path
from types import SimpleNamespace

from celery import shared_task
from django.conf import settings
from django.db import InterfaceError, OperationalError, transaction
from django.utils import timezone

from .models import (
    AgentObservation,
    EvaluationBatch,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationDataset,
    EvaluationRun,
)
from .services.evaluation import SCORER_VERSION, summarize_results
from .services.ingestion_jobs import dispatch_due_ingestion_jobs, process_ingestion_job


@shared_task(acks_late=True, reject_on_worker_lost=True)
def ingest_document_task(job_id: str) -> dict:
    """At-least-once worker entry; the durable job UUID is the idempotency key."""
    return process_ingestion_job(str(job_id))


@shared_task
def dispatch_document_ingestion_outbox() -> dict:
    """Recover broker outages and workers lost after a message was accepted."""
    return {"dispatched": dispatch_due_ingestion_jobs()}


def _snapshot_passed(metrics: dict, annotation: dict) -> tuple[bool, str]:
    metric_names = ("answer_correctness", "faithfulness", "citation_accuracy", "citation_coverage")
    thresholds = (0.90, 0.90, 0.95, 0.90)
    values = [metrics[name] for name in metric_names]
    required = [item for item in values if item.get("status") != "not_applicable"]
    should_refuse = annotation.get("should_refuse") is True
    refusal = metrics.get("refusal_quality", {})
    refusal_ok = not should_refuse or (refusal.get("status") == "scored" and refusal.get("score", 0) >= 0.95)
    scored = (bool(required) or should_refuse) and all(
        item.get("status") == "scored" and item.get("score") is not None for item in required
    )
    threshold_ok = all(
        item.get("status") == "not_applicable" or (item.get("score") is not None and item["score"] >= threshold)
        for item, threshold in zip(values, thresholds, strict=True)
    )
    passed = bool(scored and refusal_ok and threshold_ok and metrics.get("tool_success_rate", 0) >= 0.8)
    known_failure = (
        not refusal_ok
        or metrics.get("tool_success_rate", 0) < 0.8
        or any(
            item.get("status") == "scored" and item.get("score") is not None and item["score"] < threshold
            for item, threshold in zip(values, thresholds, strict=True)
        )
    )
    return passed, "passed" if passed else ("failed" if known_failure else "needs_review")


@shared_task(
    bind=True,
    autoretry_for=(OperationalError, InterfaceError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=2,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_evaluation_batch_task(self, batch_id: int) -> dict:
    """Run frozen case snapshots at least once, persisting each case atomically.

    Completed case rows are idempotency boundaries. Broker redelivery resumes pending
    work and does not repeat saved rows; model calls in the crash window before a result
    commit can still be repeated, which is recorded as an at-least-once limitation.
    """
    batch = EvaluationBatch.objects.select_related("dataset").get(pk=batch_id)
    if batch.status in {EvaluationBatch.Status.COMPLETED, EvaluationBatch.Status.FAILED}:
        return {"batch_id": batch.id, "status": batch.status, "skipped": "terminal"}
    if (
        batch.dataset.status != EvaluationDataset.Status.FROZEN
        or batch.dataset.workspace_key != batch.workspace_key
        or not batch.dataset.snapshot
    ):
        batch.status = EvaluationBatch.Status.FAILED
        batch.finished_at = timezone.now()
        batch.metadata = dict(batch.metadata)
        batch.metadata["failure_reason"] = "invalid_dataset_snapshot"
        batch.save(update_fields=["status", "finished_at", "metadata"])
        return {"batch_id": batch.id, "status": batch.status, "error": "invalid_dataset_snapshot"}
    execution_id = str(getattr(self.request, "id", "") or "worker")
    now = timezone.now()
    with transaction.atomic():
        batch = EvaluationBatch.objects.select_for_update().get(pk=batch_id)
        batch.status = EvaluationBatch.Status.RUNNING
        batch.started_at = batch.started_at or now
        batch.save(update_fields=["status", "started_at"])

    for result_id in batch.case_results.order_by("order").values_list("id", flat=True):
        with transaction.atomic():
            result = EvaluationCaseResult.objects.select_for_update().select_related("batch").get(pk=result_id)
            if result.status in {
                EvaluationCaseResult.Status.COMPLETED,
                EvaluationCaseResult.Status.NEEDS_REVIEW,
                EvaluationCaseResult.Status.SKIPPED,
            }:
                continue
            if result.status == EvaluationCaseResult.Status.RUNNING and result.claim_task_id != execution_id:
                continue
            is_redelivery = (
                result.status == EvaluationCaseResult.Status.RUNNING and result.claim_task_id == execution_id
            )
            result.status = EvaluationCaseResult.Status.RUNNING
            result.claim_task_id = execution_id
            result.started_at = result.started_at or now
            result.attempts += 0 if is_redelivery else 1
            result.save(update_fields=["status", "claim_task_id", "started_at", "attempts"])
            case_snapshot = result.case_snapshot

        try:
            from agent.multi_agent import MultiAgentSupervisor

            from .views.common import create_agent_observation, evaluate_answer

            case = SimpleNamespace(
                pk=case_snapshot["database_case_id"],
                question=case_snapshot["question"],
                workspace_key=batch.workspace_key,
                category=case_snapshot["category"],
                expected_agent=case_snapshot.get("expected_agent", ""),
                expected_route=case_snapshot.get("expected_route", ""),
                reference_keywords=case_snapshot.get("reference_keywords", []),
                annotation=case_snapshot.get("annotation", {}),
            )
            response = MultiAgentSupervisor(Path(settings.BASE_DIR).parent, workspace_key=batch.workspace_key).chat(
                case.question
            )
            response_data = response.to_dict()
            observation = create_agent_observation(
                conversation=None,
                agent_run=None,
                input_message=case.question,
                workspace_key=batch.workspace_key,
                response_data=response_data,
                latency_ms=round((timezone.now() - result.started_at).total_seconds() * 1000),
            )
            metrics = evaluate_answer(case, response_data, observation)
            passed, evaluation_status = _snapshot_passed(metrics, case.annotation)
            metrics["evaluation_status"] = evaluation_status
            with transaction.atomic():
                run = EvaluationRun.objects.create(
                    case_id=case_snapshot["database_case_id"],
                    workspace_key=batch.workspace_key,
                    observation=observation,
                    answer=response_data.get("answer", ""),
                    metrics=metrics,
                    passed=passed,
                )
                result = EvaluationCaseResult.objects.select_for_update().get(pk=result_id)
                result.evaluation_run = run
                result.passed = passed
                result.status = (
                    EvaluationCaseResult.Status.NEEDS_REVIEW
                    if evaluation_status == "needs_review"
                    else EvaluationCaseResult.Status.COMPLETED
                )
                result.finished_at = timezone.now()
                result.error = ""
                result.save(update_fields=["evaluation_run", "passed", "status", "finished_at", "error"])
        except (OperationalError, InterfaceError):
            raise
        except Exception as exc:
            with transaction.atomic():
                observation = AgentObservation.objects.create(
                    input_message=case_snapshot.get("question", ""),
                    workspace_key=batch.workspace_key,
                    status=AgentObservation.Status.FAILED,
                    failure_reason=str(exc),
                )
                case_id = case_snapshot.get("database_case_id")
                run = None
                if EvaluationCase.objects.filter(pk=case_id).exists():
                    run = EvaluationRun.objects.create(
                        case_id=case_id,
                        workspace_key=batch.workspace_key,
                        observation=observation,
                        metrics={
                            "scorer_version": SCORER_VERSION,
                            "evaluation_status": "failed",
                            "failure_reason": str(exc),
                        },
                        passed=False,
                    )
                result = EvaluationCaseResult.objects.select_for_update().get(pk=result_id)
                result.evaluation_run = run
                result.status = EvaluationCaseResult.Status.FAILED
                result.error = str(exc)[:4000]
                result.finished_at = timezone.now()
                result.save(update_fields=["evaluation_run", "status", "error", "finished_at"])

    with transaction.atomic():
        batch = EvaluationBatch.objects.select_for_update().get(pk=batch_id)
        summary = summarize_results(list(batch.case_results.values("status", "passed")))
        if summary["pending"]:
            batch.status = EvaluationBatch.Status.PARTIAL
        elif summary["errors"] == summary["total"] and summary["total"]:
            batch.status = EvaluationBatch.Status.FAILED
        elif summary["errors"]:
            batch.status = EvaluationBatch.Status.PARTIAL
        else:
            batch.status = EvaluationBatch.Status.COMPLETED
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "finished_at"])
    return {"batch_id": batch_id, "status": batch.status, "summary": summary}
