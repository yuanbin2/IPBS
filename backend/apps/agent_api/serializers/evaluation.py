from rest_framework import serializers

from ..models import EvaluationCase, EvaluationRun


class EvaluationRunSerializer(serializers.ModelSerializer):
    case_id = serializers.IntegerField(read_only=True)
    observation_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = EvaluationRun
        fields = ["id", "case_id", "observation_id", "answer", "metrics", "passed", "created_at"]


class EvaluationCaseSerializer(serializers.ModelSerializer):
    latest_run = serializers.SerializerMethodField()

    class Meta:
        model = EvaluationCase
        fields = [
            "id", "question", "expected_answer", "category", "expected_route",
            "expected_agent", "reference_keywords", "is_active", "created_at",
            "latest_run",
        ]

    def get_latest_run(self, instance):
        latest = instance.runs.first()
        return EvaluationRunSerializer(latest).data if latest else None


def serialize_evaluation_case(instance):
    return EvaluationCaseSerializer(instance).data


def serialize_evaluation_run(instance):
    return EvaluationRunSerializer(instance).data
