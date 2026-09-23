"""评估集、评估运行与可观测性测试。"""

from unittest.mock import patch

from django.test import TestCase

from ..models import AgentObservation, EvaluationCase, EvaluationRun
from .support import NO_MODEL_ENV


class EvaluationObservabilityTests(TestCase):

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_observability_dashboard_lists_agent_runs(self):
        self.client.post(
            "/api/agent/chat/",
            {"message": "帮我计算 4 + 6"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        response = self.client.get("/api/agent/observability/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["total_runs"], 1)
        self.assertEqual(payload["observations"][0]["status"], AgentObservation.Status.SUCCESS)

    def test_evaluation_dataset_contains_default_cases(self):
        response = self.client.get("/api/agent/evaluation-cases/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 30)
        self.assertIn("jailbreak", {item["category"] for item in payload})

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_evaluation_run_records_metrics(self):
        case = EvaluationCase.objects.filter(category=EvaluationCase.Category.COMPLEX).first()

        response = self.client.post(
            "/api/agent/evaluation-runs/",
            {"case_id": case.id},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(EvaluationRun.objects.count(), 1)
        self.assertIn("answer_correctness", payload["runs"][0]["metrics"])
