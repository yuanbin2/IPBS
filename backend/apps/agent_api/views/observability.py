"""可观测与评估：观测面板、评估集与评估运行。"""

import time
from pathlib import Path

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.multi_agent import MultiAgentSupervisor

from ..models import AgentObservation, EvaluationCase, EvaluationRun, UserProfile
from ..serializers import serialize_agent_observation, serialize_evaluation_case, serialize_evaluation_run
from .common import create_agent_observation, evaluate_answer, get_workspace_key, observability_summary, require_roles


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


class EvaluationRunView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        case_id = request.data.get("case_id")
        limit = request.data.get("limit", 5)
        try:
            limit = max(1, min(int(limit), 30))
        except (TypeError, ValueError):
            limit = 5

        workspace_key = get_workspace_key(request)
        if case_id:
            cases = [get_object_or_404(EvaluationCase, pk=case_id, workspace_key=workspace_key)]
        else:
            cases = list(EvaluationCase.objects.filter(is_active=True, workspace_key=workspace_key)[:limit])

        runs = [self._run_case(case) for case in cases]
        passed_count = sum(1 for run in runs if run.passed)
        return Response(
            {
                "total": len(runs),
                "passed": passed_count,
                "pass_rate": round(passed_count / len(runs), 2) if runs else 0,
                "runs": [serialize_evaluation_run(run) for run in runs],
            }
        )

    def _run_case(self, case: EvaluationCase) -> EvaluationRun:
        started_at = time.perf_counter()
        try:
            response = MultiAgentSupervisor(Path(settings.BASE_DIR).parent).chat(case.question)
            response_data = response.to_dict()
            observation = create_agent_observation(
                conversation=None,
                agent_run=None,
                input_message=case.question,
                workspace_key=case.workspace_key,
                response_data=response_data,
                latency_ms=round((time.perf_counter() - started_at) * 1000),
            )
            metrics = evaluate_answer(case, response_data, observation)
            passed = (
                metrics["answer_correctness"] >= 0.6
                and metrics["faithfulness"] >= 0.7
                and metrics["tool_success_rate"] >= 0.8
            )
            return EvaluationRun.objects.create(
                case=case,
                workspace_key=case.workspace_key,
                observation=observation,
                answer=response_data.get("answer", ""),
                metrics=metrics,
                passed=passed,
            )
        except Exception as exc:
            observation = create_agent_observation(
                conversation=None,
                agent_run=None,
                input_message=case.question,
                workspace_key=case.workspace_key,
                latency_ms=round((time.perf_counter() - started_at) * 1000),
                failure_reason=str(exc),
            )
            return EvaluationRun.objects.create(
                case=case,
                workspace_key=case.workspace_key,
                observation=observation,
                answer="",
                metrics={
                    "answer_correctness": 0,
                    "faithfulness": 0,
                    "citation_accuracy": 0,
                    "latency_ms": observation.latency_ms,
                    "tool_success_rate": 0,
                    "failure_reason": str(exc),
                },
                passed=False,
            )
