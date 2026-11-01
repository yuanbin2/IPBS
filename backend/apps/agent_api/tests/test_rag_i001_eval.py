"""I-001 frozen snapshot and reporting guardrails."""

import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from ..services.rag.evaluate_i001 import VARIANTS, evaluate, load_frozen_data

DATA = Path(__file__).resolve().parents[1] / "eval_data"


class I001EvaluationTests(SimpleTestCase):
    def test_frozen_dataset_has_separate_splits_and_required_risks(self):
        corpus, questions = load_frozen_data(DATA / "i001_corpus_v1.json", DATA / "i001_questions_v1.json")
        self.assertEqual(len(corpus["chunks"]), 28)
        self.assertGreaterEqual(len(questions["cases"]), 30)
        self.assertEqual(sum(case["split"] == "validation" for case in questions["cases"]), 14)
        self.assertEqual(questions["annotation_status"], "assistant_draft_unreviewed")

    def test_local_ablation_reports_actual_hits_and_unknown_answer_cost(self):
        corpus, questions = load_frozen_data(DATA / "i001_corpus_v1.json", DATA / "i001_questions_v1.json")
        result = evaluate(corpus, questions, embedding="local_hash")
        self.assertEqual(result["weights"], {"vector": 0.72, "keyword": 0.28, "rerank": 0.4})
        self.assertEqual(set(result["summary"]["validation"]), set(VARIANTS))
        self.assertEqual(result["summary"]["validation"]["keyword"]["answerable"], 10)
        self.assertEqual(result["summary"]["validation"]["keyword"]["no_answer_cases"], 4)
        self.assertIsNone(result["answer_evidence"]["groundedness"])
        self.assertIsNone(result["answer_evidence"]["full_request_cost"])
        self.assertTrue(all(len(row["top5"]) <= 5 and len(row["top10"]) <= 10 for row in result["rows"]))
        keyword = result["summary"]["validation"]["keyword"]
        self.assertEqual(
            keyword["recall_hits"],
            sum(
                bool(set(row["top5"]) & set(row["gold"]))
                for row in result["rows"]
                if row["split"] == "validation" and row["variant"] == "keyword" and row["gold"]
            ),
        )

    def test_unreviewed_answer_evidence_cannot_become_ground_truth(self):
        corpus, questions = load_frozen_data(DATA / "i001_corpus_v1.json", DATA / "i001_questions_v1.json")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            path.write_text(
                json.dumps({"records": [{"case_id": "q01", "review_status": "draft", "grounded": True}]}),
                encoding="utf-8",
            )
            result = evaluate(corpus, questions, embedding="local_hash", answer_records=path)
        self.assertIsNone(result["answer_evidence"]["groundedness"])
        self.assertEqual(result["answer_evidence"]["groundedness_reviewed_cases"], 0)
        self.assertIsNone(result["answer_evidence"]["full_request_cost"])

    def test_partial_i005_cost_is_not_a_complete_request_total(self):
        corpus, questions = load_frozen_data(DATA / "i001_corpus_v1.json", DATA / "i001_questions_v1.json")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            path.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "case_id": "q01",
                                "review_status": "human_reviewed",
                                "reviewer": "fixture-reviewer",
                                "grounded": True,
                                "model_accounting": {
                                    "complete_cost": True,
                                    "known_cost": "0.01",
                                    "price_version": "fixture-v1",
                                    "currency": "USD",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = evaluate(corpus, questions, embedding="local_hash", answer_records=path)
        self.assertEqual(result["answer_evidence"]["groundedness"], 1.0)
        self.assertEqual(result["answer_evidence"]["groundedness_reviewed_cases"], 1)
        self.assertFalse(result["answer_evidence"]["cost_complete"])
        self.assertIsNone(result["answer_evidence"]["full_request_cost"])
