"""Real model chunks, SSE reconstruction, and terminal run consistency."""

import json
import time
import uuid
from pathlib import Path
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from agent.model_accounting import collect_model_calls, model_purpose
from agent.multi_agent import MultiAgentSupervisor

from ..models import AgentRun, Message
from .support import NO_MODEL_ENV, OperatorApiTestCase


def decode_events(response):
    return [json.loads(chunk.decode("utf-8").removeprefix("data: ")) for chunk in response.streaming_content]


def reconstructed_answer(events):
    answer = ""
    for event in events:
        if event["type"] == "answer_delta":
            answer += event["text"]
        elif event["type"] == "answer_snapshot":
            answer = event["text"]
    return answer


class StreamingBodyTests(OperatorApiTestCase):
    def _post(self, run_id):
        return self.client.post(
            "/api/agent/chat/stream/",
            {"message": "你好", "run_id": str(run_id)},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

    def test_sse_model_calls_are_persisted_after_generator_finishes(self):
        run_id = uuid.uuid4()

        def model(*_args, **_kwargs):
            with model_purpose("query_rewrite"):
                FakeListChatModel(responses=["rewritten"]).invoke("private input")
            yield {"type": "answer_delta", "text": "完成"}
            yield {"type": "response", "answer": "完成", "sources": [], "trace": []}

        with patch("apps.agent_api.views.chat.MultiAgentSupervisor.chat_stream", side_effect=model):
            events = decode_events(self._post(run_id))
        run = AgentRun.objects.get(run_id=run_id)
        self.assertEqual(run.model_accounting["call_count"], 1)
        self.assertEqual(run.model_calls[0]["purpose"], "query_rewrite")
        self.assertEqual(
            next(event for event in events if event["type"] == "response")["model_accounting"], run.model_accounting
        )

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_langgraph_generate_node_emits_real_model_chunks_before_final_answer(self):
        supervisor = MultiAgentSupervisor(Path("."))
        supervisor.rag_agent.llm = FakeListChatModel(responses=["第一段。第二段。第三段。第四段。"])
        events = list(supervisor.chat_stream("你好"))
        kinds = [event["type"] for event in events]
        self.assertIn("answer_delta", kinds)
        self.assertLess(kinds.index("answer_delta"), kinds.index("response"))
        self.assertEqual(reconstructed_answer(events), events[-1]["answer"])

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_langgraph_stream_propagates_accounting_to_generate_node(self):
        supervisor = MultiAgentSupervisor(Path("."))
        supervisor.rag_agent.llm = FakeListChatModel(responses=["回答。"])
        with collect_model_calls(uuid.uuid4()) as collector:
            list(supervisor.chat_stream("你好"))
        self.assertEqual(len(collector.calls), 1)
        self.assertEqual(collector.calls[0]["purpose"], "direct_answer")

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_fragmented_secret_is_not_exposed_in_model_deltas(self):
        supervisor = MultiAgentSupervisor(Path("."))
        supervisor.rag_agent.llm = FakeListChatModel(responses=["普通回答。第二句。sk-abcdefghijklmnop 后续文字。"])
        events = list(supervisor.chat_stream("你好"))
        self.assertTrue(all("sk-abcdefghijklmnop" not in event.get("text", "") for event in events))
        self.assertNotIn("sk-abcdefghijklmnop", reconstructed_answer(events))
        self.assertEqual(reconstructed_answer(events), events[-1]["answer"])
        self.assertIn("[REDACTED_SECRET]", events[-1]["answer"])

    def test_sse_delta_precedes_commit_and_final_matches_persisted_answer(self):
        run_id = uuid.uuid4()
        answer = "第一段。第二段。第三段。"

        def model(*_args, **_kwargs):
            yield {"type": "trace", "data": "生成中"}
            yield {"type": "answer_delta", "text": "第一段。"}
            yield {"type": "answer_delta", "text": "第二段。"}
            yield {"type": "answer_delta", "text": "第三段。"}
            yield {"type": "response", "answer": answer, "sources": [{"document_title": "资料"}], "trace": []}

        with patch("apps.agent_api.views.chat.MultiAgentSupervisor.chat_stream", side_effect=model):
            response = self._post(run_id)
            iterator = iter(response.streaming_content)
            first = json.loads(next(iterator).decode("utf-8").removeprefix("data: "))
            self.assertEqual(first["status"], AgentRun.Status.RUNNING)
            self.assertEqual(AgentRun.objects.get(run_id=run_id).status, AgentRun.Status.RUNNING)
            events = [first, *(json.loads(chunk.decode("utf-8").removeprefix("data: ")) for chunk in iterator)]

        final = next(event for event in events if event["type"] == "response")
        self.assertEqual(reconstructed_answer(events), final["answer"])
        self.assertEqual(final["sources"][0]["document_title"], "资料")
        self.assertIsNotNone(final["first_body_ms"])
        self.assertLessEqual(final["first_body_ms"], final["latency_ms"])
        run = AgentRun.objects.get(run_id=run_id)
        self.assertEqual(run.result["answer"], answer)
        self.assertEqual(run.messages.get(role=Message.Role.AGENT).content, answer)
        self.assertEqual(events[-1]["status"], AgentRun.Status.SUCCEEDED)

    def test_close_after_first_delta_drains_model_and_saves_final_answer(self):
        run_id = uuid.uuid4()

        def model(*_args, **_kwargs):
            yield {"type": "answer_delta", "text": "前半段"}
            yield {"type": "answer_delta", "text": "后半段"}
            yield {"type": "response", "answer": "前半段后半段", "trace": []}

        with patch("apps.agent_api.views.chat.MultiAgentSupervisor.chat_stream", side_effect=model):
            response = self._post(run_id)
            iterator = iter(response.streaming_content)
            next(iterator)  # run
            first_body = json.loads(next(iterator).decode("utf-8").removeprefix("data: "))
            self.assertEqual(first_body["type"], "answer_delta")
            response.close()
        run = AgentRun.objects.get(run_id=run_id)
        self.assertEqual(run.status, AgentRun.Status.SUCCEEDED)
        self.assertEqual(run.result["answer"], "前半段后半段")

    def test_provider_without_chunks_returns_final_only_with_explicit_progress(self):
        run_id = uuid.uuid4()
        with patch(
            "apps.agent_api.views.chat.MultiAgentSupervisor.chat_stream",
            return_value=iter([{"type": "response", "answer": "完整答复", "trace": []}]),
        ):
            events = decode_events(self._post(run_id))
        self.assertNotIn("answer_delta", [event["type"] for event in events])
        self.assertIn("不提供生成期正文增量", " ".join(event.get("detail", "") for event in events))
        self.assertEqual(AgentRun.objects.get(run_id=run_id).result["first_body_ms"], None)

    def test_partial_answer_then_timeout_is_failed_without_assistant_message(self):
        run_id = uuid.uuid4()

        def model(*_args, **_kwargs):
            yield {"type": "answer_delta", "text": "未完成"}
            raise TimeoutError("model timed out")

        with patch("apps.agent_api.views.chat.MultiAgentSupervisor.chat_stream", side_effect=model):
            events = decode_events(self._post(run_id))
        self.assertEqual([event["type"] for event in events], ["run", "answer_delta", "error", "done"])
        run = AgentRun.objects.get(run_id=run_id)
        self.assertEqual(run.status, AgentRun.Status.FAILED)
        self.assertEqual(run.error_code, "TimeoutError")
        self.assertEqual(run.messages.filter(role=Message.Role.AGENT).count(), 0)

    def test_running_cancel_after_chunk_discards_partial_answer(self):
        run_id = uuid.uuid4()

        def model(*_args, **_kwargs):
            yield {"type": "answer_delta", "text": "部分文字"}
            yield {"type": "answer_delta", "text": "更多文字"}
            yield {"type": "response", "answer": "部分文字更多文字", "trace": []}

        with patch("apps.agent_api.views.chat.MultiAgentSupervisor.chat_stream", side_effect=model):
            response = self._post(run_id)
            iterator = iter(response.streaming_content)
            next(iterator)  # run
            next(iterator)  # first answer_delta
            cancellation = self.client.post(f"/api/agent/chat/runs/{run_id}/cancel/", HTTP_HOST="localhost")
            self.assertTrue(cancellation.json()["cancel_requested"])
            time.sleep(0.3)
            events = [json.loads(chunk.decode("utf-8").removeprefix("data: ")) for chunk in iterator]
        self.assertEqual(events[-1]["status"], AgentRun.Status.CANCELLED)
        self.assertEqual(AgentRun.objects.get(run_id=run_id).messages.filter(role=Message.Role.AGENT).count(), 0)

    def test_snapshot_repairs_provider_final_answer_mismatch(self):
        run_id = uuid.uuid4()
        with patch(
            "apps.agent_api.views.chat.MultiAgentSupervisor.chat_stream",
            return_value=iter(
                [{"type": "answer_delta", "text": "草稿"}, {"type": "response", "answer": "正式答案", "trace": []}]
            ),
        ):
            events = decode_events(self._post(run_id))
        self.assertEqual(reconstructed_answer(events), "正式答案")
        self.assertIn("answer_snapshot", [event["type"] for event in events])
        self.assertEqual(AgentRun.objects.get(run_id=run_id).result["answer"], "正式答案")
