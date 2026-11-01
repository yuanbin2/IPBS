"""Model callback accounting: calls, partial prices, retries and privacy."""

import json
import uuid

from django.test import SimpleTestCase
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from agent.model_accounting import collect_model_calls, model_purpose, model_retry_group

PRICE_BOOK = {
    "version": "test-2026-10-22",
    "currency": "USD",
    "units_per_token_price": 1000000,
    "models": {"priced-model": {"input": "2", "output": "8"}},
}


def finish(collector, model, usage, *, group=None, error=None, purpose="answer_generation"):
    call_id = uuid.uuid4()
    with model_purpose(purpose):
        with model_retry_group(group or str(call_id)):
            collector.on_chat_model_start(
                {"kwargs": {"api_key": "sk-private"}},
                [[HumanMessage(content="private prompt")]],
                run_id=call_id,
                invocation_params={"model_name": model, "api_key": "sk-private"},
            )
            if error:
                collector.on_llm_error(error, run_id=call_id)
            else:
                message = (
                    AIMessage(content="private answer", usage_metadata=usage)
                    if usage
                    else AIMessage(content="private answer")
                )
                collector.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=call_id)


class ModelAccountingTests(SimpleTestCase):
    def test_multiple_calls_unknown_usage_and_unknown_price_are_not_zero(self):
        with collect_model_calls(uuid.uuid4(), PRICE_BOOK) as collector:
            finish(
                collector,
                "priced-model",
                {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                purpose="query_expansion",
            )
            finish(collector, "priced-model", None, purpose="query_rewrite")
            finish(collector, "unpriced-model", {"input_tokens": 30, "output_tokens": 10, "total_tokens": 40})
        summary = collector.summary()
        self.assertEqual(summary["call_count"], 3)
        self.assertEqual(
            summary["token_usage"], {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
        )
        self.assertEqual(summary["unknown_usage_calls"], 1)
        self.assertEqual(summary["unknown_cost_calls"], 2)
        self.assertEqual(summary["known_cost"], "0.00036")
        self.assertFalse(summary["complete_cost"])
        self.assertEqual(summary["price_version"], PRICE_BOOK["version"])
        self.assertNotIn("private", json.dumps(collector.calls))
        self.assertNotIn("sk-private", json.dumps(collector.calls))

    def test_explicit_retry_records_both_attempts_and_unknown_failure_usage(self):
        with collect_model_calls(uuid.uuid4(), PRICE_BOOK) as collector:
            finish(collector, "priced-model", None, group="rewrite-1", error=TimeoutError("private payload"))
            finish(
                collector,
                "priced-model",
                {"input_tokens": 50, "output_tokens": 5, "total_tokens": 55},
                group="rewrite-1",
            )
        summary = collector.summary()
        self.assertEqual([call["attempt"] for call in collector.calls], [1, 2])
        self.assertEqual(summary["failed_calls"], 1)
        self.assertEqual(summary["known_cost"], "0.00014")
        self.assertEqual(summary["unknown_cost_calls"], 1)
        self.assertEqual(collector.calls[0]["error_type"], "TimeoutError")
        self.assertNotIn("private payload", json.dumps(collector.calls))

    def test_two_priced_successes_sum_once(self):
        with collect_model_calls(uuid.uuid4(), PRICE_BOOK) as collector:
            finish(collector, "priced-model", {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12})
            finish(collector, "priced-model", {"input_tokens": 20, "output_tokens": 3, "total_tokens": 23})
        summary = collector.summary()
        self.assertEqual(summary["token_usage"], {"prompt_tokens": 30, "completion_tokens": 5, "total_tokens": 35})
        self.assertEqual(summary["known_cost"], "0.000100")
        self.assertEqual(summary["unknown_cost_calls"], 0)
        self.assertEqual(collector.summary(), summary)

    def test_langchain_callback_hook_captures_real_runnable_and_does_not_leak_between_runs(self):
        with collect_model_calls(uuid.uuid4(), PRICE_BOOK) as first:
            with model_purpose("query_expansion"):
                FakeListChatModel(responses=["ok"]).invoke("private prompt")
        with collect_model_calls(uuid.uuid4(), PRICE_BOOK) as second:
            FakeListChatModel(responses=["ok"]).invoke("other prompt")
        self.assertEqual(len(first.calls), 1)
        self.assertEqual(first.calls[0]["purpose"], "query_expansion")
        self.assertEqual(first.calls[0]["token_usage"]["total_tokens"], None)
        self.assertEqual(second.calls[0]["purpose"], "answer_generation")
        self.assertNotEqual(first.calls[0]["run_id"], second.calls[0]["run_id"])

    def test_no_model_call_is_known_zero(self):
        with collect_model_calls(uuid.uuid4(), PRICE_BOOK) as collector:
            pass
        summary = collector.summary()
        self.assertEqual(summary["token_usage"]["total_tokens"], 0)
        self.assertEqual(summary["unknown_cost_calls"], 0)
        self.assertTrue(summary["complete_cost"])
