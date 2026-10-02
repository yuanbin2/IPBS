"""可观测与评估：观测面板、评估集与评估运行。"""

import uuid

from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import (
    AgentObservation,
    EvaluationBatch,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationDataset,
    UserProfile,
)
from ..serializers import (
    serialize_agent_observation,
    serialize_evaluation_batch,
    serialize_evaluation_case,
    serialize_evaluation_dataset,
)
from ..services.evaluation import (
    MAX_BATCH_CASES,
    MAX_DATASET_CASES,
    batches_comparable,
    collect_run_provenance,
    content_hash,
    snapshot_case,
)
from .common import get_workspace_key, observability_summary, require_roles


class ObservabilityDashboardView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        limit = min(int(request.query_params.get("limit", 10)), 100)
        offset = max(int(request.query_params.get("offset", 0)), 0)
        queryset = (
            AgentObservation.objects.select_related("conversation", "agent_run")
            .filter(workspace_key=get_workspace_key(request))
            .order_by("-id")
        )
        total = queryset.count()
        observations = queryset[offset : offset + limit]
        return Response(
            {
                "summary": observability_summary(get_workspace_key(request)),
                "observations": [serialize_agent_observation(observation) for observation in observations],
                "total": total,
                "has_more": offset + limit < total,
            }
        )


class EvaluationCaseListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        category = request.query_params.get("category")
        cases = EvaluationCase.objects.prefetch_related("runs").filter(workspace_key=get_workspace_key(request))
        if category and category != "all":
            cases = cases.filter(category=category)
        return Response([serialize_evaluation_case(case) for case in cases])


def _dispatch_evaluation_batch(batch: EvaluationBatch) -> None:
    if batch.status != EvaluationBatch.Status.QUEUED or batch.celery_task_id:
        return
    try:
        from ..tasks import run_evaluation_batch_task

        task = run_evaluation_batch_task.delay(batch.id)
        EvaluationBatch.objects.filter(pk=batch.pk, status=EvaluationBatch.Status.QUEUED).update(celery_task_id=task.id)
    except Exception as exc:
        # The committed batch remains queryable and can be re-dispatched by an
        # idempotent client retry if broker publication is temporarily unavailable.
        metadata = dict(batch.metadata)
        metadata["dispatch_error"] = type(exc).__name__
        EvaluationBatch.objects.filter(pk=batch.pk, status=EvaluationBatch.Status.QUEUED).update(metadata=metadata)


def _create_batch(dataset, workspace_key, limit, actor, idempotency_key):
    selected = dataset.snapshot[:limit]
    request_hash = content_hash(
        {"dataset_hash": dataset.manifest_hash, "case_keys": [item["case_key"] for item in selected]}
    )
    existing = EvaluationBatch.objects.filter(workspace_key=workspace_key, idempotency_key=idempotency_key).first()
    if existing:
        if existing.request_hash != request_hash:
            return None, "Idempotency-Key was already used for a different evaluation request."
        if existing.status == EvaluationBatch.Status.QUEUED and not existing.celery_task_id:
            _dispatch_evaluation_batch(existing)
        return existing, ""

    metadata = collect_run_provenance(dataset, expected_case_count=len(selected))
    try:
        with transaction.atomic():
            batch = EvaluationBatch.objects.create(
                dataset=dataset,
                workspace_key=workspace_key,
                total_cases=len(selected),
                metadata=metadata,
                request_hash=request_hash,
                idempotency_key=idempotency_key,
                created_by=actor,
            )
            EvaluationCaseResult.objects.bulk_create(
                [
                    EvaluationCaseResult(
                        batch=batch,
                        case_key=item["case_key"],
                        order=index,
                        case_snapshot=item,
                    )
                    for index, item in enumerate(selected, start=1)
                ]
            )
            transaction.on_commit(
                lambda batch_id=batch.id: _dispatch_evaluation_batch(EvaluationBatch.objects.get(pk=batch_id))
            )
    except IntegrityError:
        existing = EvaluationBatch.objects.filter(workspace_key=workspace_key, idempotency_key=idempotency_key).first()
        if existing:
            if existing.request_hash != request_hash:
                return None, "Idempotency-Key was already used for a different evaluation request."
            return existing, ""
        return None, "An evaluation batch is already queued or running in this workspace."
    return batch, ""


class EvaluationDatasetView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        datasets = EvaluationDataset.objects.filter(workspace_key=get_workspace_key(request))
        return Response([serialize_evaluation_dataset(item) for item in datasets])

    def post(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        workspace_key = get_workspace_key(request)
        version = str(request.data.get("version", "")).strip()
        case_ids = request.data.get("case_ids")
        if not version or len(version) > 80:
            return Response({"detail": "version is required and must be at most 80 characters."}, status=400)
        if case_ids is None:
            cases = list(EvaluationCase.objects.filter(workspace_key=workspace_key, is_active=True)[:MAX_DATASET_CASES])
        elif isinstance(case_ids, list) and 0 < len(case_ids) <= MAX_DATASET_CASES:
            cases = list(EvaluationCase.objects.filter(workspace_key=workspace_key, pk__in=case_ids))
            if len(cases) != len(set(case_ids)):
                return Response({"detail": "case_ids must be unique and belong to this workspace."}, status=400)
        else:
            return Response({"detail": f"case_ids must contain 1 to {MAX_DATASET_CASES} IDs."}, status=400)
        if not cases:
            return Response({"detail": "No evaluation cases were selected."}, status=400)
        order = {case_id: index for index, case_id in enumerate(case_ids or [case.pk for case in cases])}
        cases.sort(key=lambda case: order.get(case.pk, case.pk))
        snapshot = [snapshot_case(case) for case in cases]
        manifest_hash = content_hash(snapshot)
        try:
            dataset = EvaluationDataset.objects.create(
                workspace_key=workspace_key,
                version=version,
                manifest_hash=manifest_hash,
                snapshot=snapshot,
                created_by=(
                    str(request.user.username)
                    if getattr(request, "user", None) and request.user.is_authenticated
                    else ""
                ),
            )
        except IntegrityError:
            return Response({"detail": "This dataset version already exists in the workspace."}, status=409)
        return Response(serialize_evaluation_dataset(dataset), status=201)


class EvaluationDatasetFreezeView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, pk):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        workspace_key = get_workspace_key(request)
        with transaction.atomic():
            try:
                dataset = EvaluationDataset.objects.select_for_update().get(pk=pk, workspace_key=workspace_key)
            except EvaluationDataset.DoesNotExist as exc:
                raise Http404 from exc
            if dataset.status != EvaluationDataset.Status.FROZEN:
                dataset.status = EvaluationDataset.Status.FROZEN
                dataset.frozen_at = timezone.now()
                dataset.save(update_fields=["status", "frozen_at"])
        return Response(serialize_evaluation_dataset(dataset))


class EvaluationBatchCreateView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        dataset_id = request.data.get("dataset_id")
        limit = request.data.get("limit", 5)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return Response({"detail": "limit must be an integer."}, status=400)
        if not 1 <= limit <= MAX_BATCH_CASES:
            return Response({"detail": f"limit must be between 1 and {MAX_BATCH_CASES}."}, status=400)
        workspace_key = get_workspace_key(request)
        dataset = get_object_or_404(EvaluationDataset, pk=dataset_id, workspace_key=workspace_key)
        if dataset.status != EvaluationDataset.Status.FROZEN:
            return Response({"detail": "Only frozen evaluation datasets can be run."}, status=409)
        if not dataset.snapshot:
            return Response({"detail": "Cannot run an empty evaluation dataset."}, status=409)
        if limit > len(dataset.snapshot):
            return Response({"detail": "limit exceeds the frozen dataset case count."}, status=400)
        key = request.headers.get("Idempotency-Key") or str(uuid.uuid4())
        if len(key) > 120:
            return Response({"detail": "Idempotency-Key must be at most 120 characters."}, status=400)
        batch, error = _create_batch(dataset, workspace_key, limit, "operator", key)
        if error:
            return Response({"detail": error}, status=409)
        return Response(serialize_evaluation_batch(batch), status=202)


class EvaluationBatchListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        batches = EvaluationBatch.objects.filter(workspace_key=get_workspace_key(request))[:50]
        return Response([serialize_evaluation_batch(item) for item in batches])


class EvaluationBatchDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, pk):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        batch = get_object_or_404(EvaluationBatch, pk=pk, workspace_key=get_workspace_key(request))
        return Response(serialize_evaluation_batch(batch))


class EvaluationBatchRetryView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, pk):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        workspace_key = get_workspace_key(request)
        with transaction.atomic():
            batch = get_object_or_404(EvaluationBatch.objects.select_for_update(), pk=pk, workspace_key=workspace_key)
            dispatch_failed = batch.status == EvaluationBatch.Status.QUEUED and "dispatch_error" in batch.metadata
            if not dispatch_failed and batch.status not in {
                EvaluationBatch.Status.PARTIAL,
                EvaluationBatch.Status.FAILED,
            }:
                return Response({"detail": "Only partial or failed batches can be retried."}, status=409)
            if dispatch_failed:
                batch.metadata = dict(batch.metadata)
                batch.metadata.pop("dispatch_error", None)
                batch.celery_task_id = ""
                batch.save(update_fields=["metadata", "celery_task_id"])
            else:
                retryable = batch.case_results.filter(status=EvaluationCaseResult.Status.FAILED, attempts__lt=3)
                if not retryable.exists():
                    return Response({"detail": "No failed cases remain within the retry limit."}, status=409)
                retryable.update(
                    status=EvaluationCaseResult.Status.PENDING, error="", finished_at=None, claim_task_id=""
                )
                batch.idempotency_key = f"retry-{batch.pk}-{uuid.uuid4()}"
            batch.status = EvaluationBatch.Status.QUEUED
            batch.finished_at = None
            batch.celery_task_id = ""
            batch.save(update_fields=["status", "finished_at", "celery_task_id", "idempotency_key"])
            transaction.on_commit(
                lambda batch_id=batch.id: _dispatch_evaluation_batch(EvaluationBatch.objects.get(pk=batch_id))
            )
        return Response(serialize_evaluation_batch(batch), status=202)


class EvaluationBatchCompareView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        batch_ids = request.data.get("batch_ids")
        if not isinstance(batch_ids, list) or len(batch_ids) != 2:
            return Response({"detail": "Exactly two batch_ids are required."}, status=400)
        batches = list(
            EvaluationBatch.objects.filter(workspace_key=get_workspace_key(request), pk__in=batch_ids).select_related(
                "dataset"
            )
        )
        if len(batches) != 2 or len({item.pk for item in batches}) != 2:
            raise Http404
        first, second = batches
        if not batches_comparable(first.metadata, second.metadata):
            return Response(
                {
                    "comparable": False,
                    "detail": "Batches have different frozen inputs/configuration or incomplete provenance.",
                    "first": {
                        "dataset_version": first.dataset.version,
                        "comparison_fingerprint": first.metadata.get("comparison_fingerprint"),
                        "unknown_provenance": first.metadata.get("unknown_provenance", []),
                    },
                    "second": {
                        "dataset_version": second.dataset.version,
                        "comparison_fingerprint": second.metadata.get("comparison_fingerprint"),
                        "unknown_provenance": second.metadata.get("unknown_provenance", []),
                    },
                },
                status=409,
            )
        return Response(
            {
                "comparable": True,
                "comparison_fingerprint": first.metadata["comparison_fingerprint"],
                "first": serialize_evaluation_batch(first),
                "second": serialize_evaluation_batch(second),
            }
        )


class EvaluationRunView(EvaluationBatchCreateView):
    """Deprecated endpoint retained as an asynchronous alias for existing clients."""

    def post(self, request):
        if request.data.get("dataset_id"):
            return super().post(request)
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        workspace_key = get_workspace_key(request)
        try:
            limit = int(request.data.get("limit", 5))
        except (TypeError, ValueError):
            return Response({"detail": "limit must be an integer."}, status=400)
        if not 1 <= limit <= MAX_BATCH_CASES:
            return Response({"detail": f"limit must be between 1 and {MAX_BATCH_CASES}."}, status=400)
        case_id = request.data.get("case_id")
        if case_id:
            cases = [get_object_or_404(EvaluationCase, pk=case_id, workspace_key=workspace_key)]
            limit = 1
        else:
            cases = list(EvaluationCase.objects.filter(workspace_key=workspace_key, is_active=True)[:limit])
        if not cases:
            return Response({"detail": "No active evaluation cases exist in this workspace."}, status=400)
        snapshot = [snapshot_case(case) for case in cases]
        manifest_hash = content_hash(snapshot)
        version = f"adhoc-{manifest_hash[:24]}"
        dataset, _ = EvaluationDataset.objects.get_or_create(
            workspace_key=workspace_key,
            version=version,
            defaults={
                "status": EvaluationDataset.Status.FROZEN,
                "manifest_hash": manifest_hash,
                "snapshot": snapshot,
                "frozen_at": timezone.now(),
                "created_by": "deprecated-evaluation-runs-api",
            },
        )
        key = request.headers.get("Idempotency-Key") or str(uuid.uuid4())
        batch, error = _create_batch(dataset, workspace_key, min(limit, len(snapshot)), "operator", key)
        if error:
            return Response({"detail": error}, status=409)
        response = serialize_evaluation_batch(batch)
        response["deprecated_async_alias"] = True
        return Response(response, status=202)
