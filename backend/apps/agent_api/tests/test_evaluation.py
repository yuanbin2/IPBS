"""评估集、评估运行与可观测性测试。"""

from unittest.mock import patch

from ..models import AgentObservation, EvaluationCase, EvaluationRun
from ..services.evaluation import SCORER_VERSION
from ..tasks import _snapshot_passed
from ..views.common import create_agent_observation, evaluate_answer
from .support import NO_MODEL_ENV, OperatorApiTestCase


class EvaluationObservabilityTests(OperatorApiTestCase):

    def make_case(self, *, should_refuse=False, facts=None, forbidden=None):
        return EvaluationCase.objects.create(
            question="test question",
            category=EvaluationCase.Category.KNOWLEDGE,
            annotation={
                "schema_version": 1,
                "review_status": "human_reviewed",
                "reviewer": "test-rubric-reviewer",
                "reviewed_at": "2026-09-29T00:00:00Z",
                "claim_review_complete": True,
                "should_refuse": should_refuse,
                "refusal_patterns": ["资料不足，无法确认", "我无法从资料确认"],
                "atomic_facts": facts or [],
                "forbidden_claims": forbidden or [],
            },
        )

    def score(self, case, answer, sources=None, tool_calls=None):
        response_data = {"answer": answer, "sources": sources or [], "tool_calls": tool_calls or []}
        observation = create_agent_observation(
            conversation=None,
            agent_run=None,
            input_message=case.question,
            workspace_key=case.workspace_key,
            response_data=response_data,
        )
        return evaluate_answer(case, response_data, observation)

    def fact_case(self):
        return self.make_case(
            facts=[
                {
                    "id": "fact-1",
                    "answer_patterns": ["项目使用 Django"],
                    "allowed_source_ids": ["chunk-allowed"],
                    "support_patterns": ["项目使用 Django"],
                    "requires_citation": True,
                }
            ]
        )

    def test_correct_answer_with_reviewed_supporting_citation_scores_and_passes(self):
        case = self.fact_case()
        response_data = {
            "answer": "项目使用 Django [1]。",
            "sources": [{"chunk_id": "chunk-allowed", "content": "项目使用 Django"}],
            "tool_calls": [{"ok": True}],
        }
        metrics = self.score(case, response_data["answer"], response_data["sources"], response_data["tool_calls"])
        passed, status = _snapshot_passed(metrics, case.annotation)
        self.assertTrue(passed)
        self.assertEqual(status, "passed")
        self.assertEqual(metrics["answer_correctness"]["score"], 1.0)
        self.assertEqual(metrics["faithfulness"]["score"], 1.0)
        self.assertEqual(metrics["citation_accuracy"]["score"], 1.0)
        self.assertEqual(metrics["citation_coverage"]["score"], 1.0)
        self.assertEqual(metrics["evidence_trace"][0]["support"], "supported")

    def test_wrong_or_unrelated_citation_fails_evidence_gate(self):
        for answer, source_id in [
            ("项目使用 Django [1]。", "wrong-chunk"),
            ("项目使用 Django [1]。", "chunk-allowed"),
        ]:
            case = self.fact_case()
            sources = [{"chunk_id": source_id, "content": "与 Django 无关的内容"}]
            metrics = self.score(case, answer, sources)
            self.assertEqual(metrics["answer_correctness"]["score"], 1.0)
            self.assertEqual(metrics["citation_accuracy"]["score"], 0.0)
            self.assertEqual(metrics["citation_coverage"]["score"], 0.0)
            self.assertEqual(metrics["faithfulness"]["score"], 0.0)
            passed, status = _snapshot_passed(metrics, case.annotation)
            self.assertFalse(passed)
            self.assertEqual(status, "failed")

    def test_zero_based_and_out_of_range_citations_cannot_reference_sources(self):
        for citation in ("[0]", "[00]", "[2]"):
            with self.subTest(citation=citation):
                metrics = self.score(
                    self.fact_case(),
                    f"项目使用 Django {citation}。",
                    [{"chunk_id": "chunk-allowed", "content": "项目使用 Django"}],
                )
                self.assertEqual(metrics["citation_accuracy"]["score"], 0.0)
                self.assertEqual(metrics["citation_coverage"]["score"], 0.0)
                self.assertEqual(metrics["faithfulness"]["score"], 0.0)

    def test_one_citation_supporting_two_facts_is_counted_once(self):
        case = self.make_case(
            facts=[
                {
                    "id": "fact-django",
                    "answer_patterns": ["后端是 Django"],
                    "allowed_source_ids": ["chunk-combined"],
                    "support_patterns": ["后端是 Django"],
                    "requires_citation": True,
                },
                {
                    "id": "fact-postgres",
                    "answer_patterns": ["数据库是 PostgreSQL"],
                    "allowed_source_ids": ["chunk-combined"],
                    "support_patterns": ["数据库是 PostgreSQL"],
                    "requires_citation": True,
                },
            ]
        )
        metrics = self.score(
            case,
            "后端是 Django，数据库是 PostgreSQL [1]。",
            [{"chunk_id": "chunk-combined", "content": "后端是 Django，数据库是 PostgreSQL"}],
        )
        self.assertEqual(metrics["citation_accuracy"]["score"], 1.0)
        self.assertEqual(metrics["citation_accuracy"]["numerator"], 1)
        self.assertEqual(metrics["citation_accuracy"]["denominator"], 1)
        self.assertEqual(metrics["citation_coverage"]["score"], 1.0)

    def test_uncited_fact_is_not_grounded_and_cannot_pass(self):
        case = self.fact_case()
        metrics = self.score(case, "项目使用 Django。", [])
        self.assertEqual(metrics["citation_accuracy"]["score"], 0.0)
        self.assertEqual(metrics["citation_accuracy"]["numerator"], 0)
        self.assertEqual(metrics["citation_accuracy"]["denominator"], 0)
        self.assertIn("无引用", metrics["citation_accuracy"]["reason"])
        self.assertEqual(metrics["citation_coverage"]["score"], 0.0)
        self.assertEqual(metrics["faithfulness"]["score"], 0.0)
        passed, status = _snapshot_passed(metrics, case.annotation)
        self.assertFalse(passed)
        self.assertEqual(status, "failed")

    def test_faithfulness_needs_visible_support_even_when_inline_citation_is_optional(self):
        case = self.make_case(
            facts=[
                {
                    "id": "fact-optional-citation",
                    "answer_patterns": ["项目使用 Django"],
                    "allowed_source_ids": ["chunk-allowed"],
                    "support_patterns": ["项目使用 Django"],
                    "requires_citation": False,
                }
            ]
        )

        supported = self.score(
            case,
            "项目使用 Django。",
            [{"chunk_id": "chunk-allowed", "content": "项目使用 Django"}],
        )
        self.assertEqual(supported["faithfulness"]["score"], 1.0)
        self.assertEqual(supported["citation_accuracy"]["status"], "not_applicable")
        self.assertEqual(supported["citation_coverage"]["status"], "not_applicable")
        self.assertEqual(supported["evidence_trace"][0]["support"], "supported")
        self.assertEqual(supported["scorer_version"], SCORER_VERSION)
        self.assertEqual(_snapshot_passed(supported, case.annotation), (True, "passed"))

        unsupported = self.score(case, "项目使用 Django。", [])
        self.assertEqual(unsupported["faithfulness"]["score"], 0.0)
        self.assertEqual(unsupported["evidence_trace"][0]["support"], "missing")
        self.assertEqual(_snapshot_passed(unsupported, case.annotation), (False, "failed"))

    def test_unmapped_extra_claim_makes_faithfulness_undetermined(self):
        case = self.fact_case()
        metrics = self.score(
            case,
            "项目使用 Django [1]。我还断定这个项目由外星人编写。",
            [{"chunk_id": "chunk-allowed", "content": "项目使用 Django"}],
        )
        self.assertEqual(metrics["answer_correctness"]["score"], 1.0)
        self.assertIsNone(metrics["faithfulness"]["score"])
        self.assertEqual(metrics["faithfulness"]["status"], "undetermined")
        self.assertEqual(metrics["evidence_trace"][-1]["unmapped_response_lines"], ["我还断定这个项目由外星人编写"])
        same_sentence = self.score(
            self.fact_case(),
            "项目使用 Django [1]，据说它是世界最大的香蕉厂。",
            [{"chunk_id": "chunk-allowed", "content": "项目使用 Django"}],
        )
        self.assertIsNone(same_sentence["faithfulness"]["score"])
        self.assertIn("据说它是世界最大的香蕉厂", same_sentence["evidence_trace"][-1]["unmapped_response_lines"][0])
        passed, status = _snapshot_passed(same_sentence, case.annotation)
        self.assertFalse(passed)
        self.assertEqual(status, "needs_review")

    def test_insufficient_material_refusal_scores_and_fabrication_fails(self):
        refusal_case = self.make_case(should_refuse=True)
        correct = self.score(refusal_case, "资料不足，无法确认。")
        fabricated = self.score(refusal_case, "项目使用 Django [1]。", [{"chunk_id": "chunk-allowed"}])
        mixed = self.score(refusal_case, "资料不足，无法确认。我还断定项目使用 Flask。")
        self.assertEqual(correct["refusal_quality"]["score"], 1.0)
        self.assertEqual(correct["evaluation_status"], "scored")
        self.assertEqual(fabricated["refusal_quality"]["score"], 0.0)
        self.assertEqual(mixed["refusal_quality"]["score"], 0.0)

        correct_metrics = self.score(refusal_case, "资料不足，无法确认。")
        correct_passed, correct_status = _snapshot_passed(correct_metrics, refusal_case.annotation)
        self.assertTrue(correct_passed)
        self.assertEqual(correct_status, "passed")
        self.assertEqual(correct_metrics["refusal_quality"]["score"], 1.0)

        fabricated_case = self.make_case(should_refuse=True)
        fabricated_metrics = self.score(
            fabricated_case,
            "项目使用 Django [1]。",
            [{"chunk_id": "chunk-allowed"}],
        )
        fabricated_passed, fabricated_status = _snapshot_passed(fabricated_metrics, fabricated_case.annotation)
        self.assertFalse(fabricated_passed)
        self.assertEqual(fabricated_status, "failed")

    def test_tool_success_is_separate_and_does_not_rescue_wrong_answer(self):
        case = self.fact_case()
        metrics = self.score(case, "项目使用 Flask [1]。", [{"chunk_id": "chunk-allowed"}], [{"ok": True}])
        self.assertEqual(metrics["tool_success_rate"], 1.0)
        self.assertEqual(metrics["answer_correctness"]["score"], 0.0)
        self.assertNotEqual(metrics["tool_success_rate"], metrics["answer_correctness"]["score"])
        passed, status = _snapshot_passed(metrics, case.annotation)
        self.assertFalse(passed)
        self.assertEqual(metrics["tool_success_rate"], 1.0)
        self.assertEqual(status, "failed")

    def test_legacy_metrics_are_preserved_and_labeled(self):
        case = self.make_case()
        run = EvaluationRun.objects.create(
            case=case,
            answer="old",
            metrics={
                "answer_correctness": 0.9,
                "faithfulness": 1.0,
                "citation_accuracy": 1.0,
            },
            passed=True,
        )
        response = self.client.get("/api/agent/evaluation-cases/", HTTP_HOST="localhost")
        serialized = next(item["latest_run"] for item in response.json() if item["id"] == case.id)
        self.assertEqual(serialized["metrics"]["answer_correctness"], 0.9)
        self.assertEqual(serialized["metrics"]["scorer_version"], "legacy-heuristic-v0")
        self.assertEqual(serialized["metrics"]["evaluation_status"], "legacy")
        self.assertEqual(run.metrics["answer_correctness"], 0.9)

    def test_unreviewed_seed_cases_are_pending_not_high_scoring(self):
        case = EvaluationCase.objects.create(question="unreviewed", category=EvaluationCase.Category.BLOG)
        metrics = self.score(case, "Django [1]。", [{"chunk_id": "any"}])
        self.assertEqual(metrics["evaluation_status"], "needs_review")
        self.assertIsNone(metrics["answer_correctness"]["score"])
        self.assertIsNone(metrics["answer_correctness"]["numerator"])
        self.assertIsNone(metrics["answer_correctness"]["denominator"])
        self.assertIsNone(metrics["citation_accuracy"]["score"])
        passed, status = _snapshot_passed(metrics, case.annotation)
        self.assertFalse(passed)
        self.assertEqual(status, "needs_review")

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
        self.assertEqual(
            len(set(EvaluationCase.objects.values_list("case_key", flat=True))),
            30,
        )

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_evaluation_run_records_metrics(self):
        case = EvaluationCase.objects.filter(category=EvaluationCase.Category.COMPLEX).first()

        response = self.client.post(
            "/api/agent/evaluation-runs/",
            {"case_id": case.id},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["status"], "queued")
        self.assertEqual(payload["summary"]["total"], 1)
        self.assertEqual(EvaluationRun.objects.count(), 0)
        self.assertEqual(payload["metadata"]["scorer_version"], SCORER_VERSION)
