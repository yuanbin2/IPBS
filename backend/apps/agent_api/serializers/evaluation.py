from rest_framework import serializers

from ..models import EvaluationBatch, EvaluationCase, EvaluationCaseResult, EvaluationDataset, EvaluationRun
from ..services.evaluation import summarize_results


class EvaluationRunSerializer(serializers.ModelSerializer):
    case_id = serializers.IntegerField(read_only=True)
    observation_id = serializers.IntegerField(read_only=True, allow_null=True)
    metrics = serializers.SerializerMethodField()

    class Meta:
        model = EvaluationRun
        fields = ["id", "case_id", "observation_id", "answer", "metrics", "passed", "created_at"]

    def get_metrics(self, instance):
        metrics = dict(instance.metrics or {})
        if not metrics.get("scorer_version"):
            metrics["scorer_version"] = "legacy-heuristic-v0"
            metrics["evaluation_status"] = "legacy"
        return metrics


class EvaluationCaseSerializer(serializers.ModelSerializer):
    latest_run = serializers.SerializerMethodField()
    annotation_status = serializers.SerializerMethodField()

    class Meta:
        model = EvaluationCase
        fields = [
            "id",
            "question",
            "expected_answer",
            "category",
            "expected_route",
            "expected_agent",
            "reference_keywords",
            "annotation",
            "annotation_status",
            "is_active",
            "created_at",
            "latest_run",
        ]

    def get_latest_run(self, instance):
        latest = instance.runs.first()
        return EvaluationRunSerializer(latest).data if latest else None

    def get_annotation_status(self, instance):
        annotation = instance.annotation if isinstance(instance.annotation, dict) else {}
        return annotation.get("review_status", "draft")


def serialize_evaluation_case(instance):
    return EvaluationCaseSerializer(instance).data


def serialize_evaluation_run(instance):
    return EvaluationRunSerializer(instance).data


class EvaluationDatasetSerializer(serializers.ModelSerializer):
    case_count = serializers.SerializerMethodField()
    human_reviewed_count = serializers.SerializerMethodField()
    draft_annotation_count = serializers.SerializerMethodField()

    class Meta:
        model = EvaluationDataset
        fields = [
            "id",
            "version",
            "status",
            "manifest_hash",
            "case_count",
            "human_reviewed_count",
            "draft_annotation_count",
            "created_at",
            "frozen_at",
        ]

    def _snapshot(self, instance):
        return instance.snapshot if isinstance(instance.snapshot, list) else []

    def get_case_count(self, instance):
        return len(self._snapshot(instance))

    def get_human_reviewed_count(self, instance):
        return sum(1 for item in self._snapshot(instance) if item.get("annotation_status") == "human_reviewed")

    def get_draft_annotation_count(self, instance):
        return sum(1 for item in self._snapshot(instance) if item.get("annotation_status") != "human_reviewed")


class EvaluationCaseResultSerializer(serializers.ModelSerializer):
    metrics = serializers.SerializerMethodField()

    class Meta:
        model = EvaluationCaseResult
        fields = [
            "id",
            "case_key",
            "order",
            "case_snapshot",
            "status",
            "passed",
            "error",
            "attempts",
            "evaluation_run_id",
            "metrics",
            "started_at",
            "finished_at",
        ]

    def get_metrics(self, instance):
        if instance.evaluation_run_id:
            return EvaluationRunSerializer(instance.evaluation_run).data["metrics"]
        return {}


class EvaluationBatchSerializer(serializers.ModelSerializer):
    summary = serializers.SerializerMethodField()
    progress_percent = serializers.SerializerMethodField()
    case_results = serializers.SerializerMethodField()

    class Meta:
        model = EvaluationBatch
        fields = [
            "id",
            "dataset_id",
            "workspace_key",
            "status",
            "total_cases",
            "metadata",
            "summary",
            "progress_percent",
            "case_results",
            "celery_task_id",
            "created_at",
            "started_at",
            "finished_at",
        ]

    def _results(self, instance):
        return list(instance.case_results.order_by("order").select_related("evaluation_run"))

    def get_summary(self, instance):
        return summarize_results([{"status": item.status, "passed": item.passed} for item in self._results(instance)])

    def get_progress_percent(self, instance):
        if not instance.total_cases:
            return 100
        summary = self.get_summary(instance)
        finished = summary["completed"] + summary["needs_review"] + summary["errors"] + summary["skipped"]
        return round(finished * 100 / instance.total_cases)

    def get_case_results(self, instance):
        return EvaluationCaseResultSerializer(self._results(instance), many=True).data


def serialize_evaluation_dataset(instance):
    return EvaluationDatasetSerializer(instance).data


def serialize_evaluation_batch(instance):
    return EvaluationBatchSerializer(instance).data
