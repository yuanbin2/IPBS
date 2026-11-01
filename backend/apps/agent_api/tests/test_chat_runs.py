"""Chat run identity, persistence, cancellation, and recovery contracts."""

import json
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from agent.agent_types import MultiAgentResponse, SupervisorDecision
from agent.model_accounting import model_purpose
from agent.simple_agent import SimpleToolCallingAgent

from ..models import AgentObservation, AgentRun, ApprovalRequest, BlogArticle, Conversation, Message, UserProfile
from ..views.chat_runs import finish_run, start_run
from .support import NO_MODEL_ENV, OperatorApiTestCase


class ChatRunTests(OperatorApiTestCase):
    @staticmethod
    def _answer():
        return MultiAgentResponse(
            answer="已核实的模拟回答",
            tool_calls=[],
            sources=[],
            trace=["mock -> completed"],
            route="direct",
            token_usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            supervisor=SupervisorDecision("rag_agent", "RAG", "mock", 1.0, "mock"),
        )

    def _post(self, path, message="你好", run_id=None, **extra):
        payload = {"message": message, **extra}
        if run_id is not None:
            payload["run_id"] = str(run_id)
        return self.client.post(path, payload, content_type="application/json", HTTP_HOST="localhost")

    def _owned_run(self, status=AgentRun.Status.PENDING, *, owner=None, workspace="default"):
        conversation = Conversation.objects.create(
            title="run", owner_username=owner or self.test_user.username, workspace_key=workspace
        )
        run = AgentRun.objects.create(
            conversation=conversation,
            workspace_key=workspace,
            input_message="你好",
            status=status,
        )
        Message.objects.create(conversation=conversation, agent_run=run, role=Message.Role.USER, content="你好")
        return run

    def test_model_calls_are_aggregated_and_persisted_once_for_duplicate_run(self):
        run_id = uuid.uuid4()

        def answer(*args, **kwargs):
            model = FakeListChatModel(responses=["expanded", "answer"])
            with model_purpose("query_expansion"):
                model.invoke("private input")
            with model_purpose("direct_answer"):
                model.invoke("private input")
            return self._answer()

        with patch("apps.agent_api.views.chat.MultiAgentSupervisor.chat", side_effect=answer) as chat:
            first = self._post("/api/agent/chat/", run_id=run_id)
            second = self._post("/api/agent/chat/", run_id=run_id)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(chat.call_count, 1)
        run = AgentRun.objects.get(run_id=run_id)
        self.assertEqual([call["purpose"] for call in run.model_calls], ["query_expansion", "direct_answer"])
        self.assertEqual(run.model_accounting["call_count"], 2)
        self.assertEqual(run.model_accounting["unknown_usage_calls"], 2)
        self.assertIsNone(run.token_usage["total_tokens"])
        self.assertEqual(len(run.messages.filter(role=Message.Role.AGENT)), 1)

    def test_failed_run_retains_model_error_without_private_content(self):
        run_id = uuid.uuid4()

        def failed(*args, **kwargs):
            with model_purpose("direct_answer"):
                FakeListChatModel(responses=["unused"]).invoke("private input")
            raise TimeoutError("private prompt and secret sk-private")

        with patch("apps.agent_api.views.chat.MultiAgentSupervisor.chat", side_effect=failed):
            response = self._post("/api/agent/chat/", run_id=run_id)
        self.assertEqual(response.status_code, 503)
        run = AgentRun.objects.get(run_id=run_id)
        self.assertEqual(run.model_accounting["call_count"], 1)
        self.assertNotIn("private", json.dumps(run.model_calls))

    def test_sync_result_messages_and_observation_are_linked_and_retry_is_idempotent(self):
        run_id = uuid.uuid4()
        with patch("apps.agent_api.views.chat.MultiAgentSupervisor.chat", return_value=self._answer()) as chat:
            first = self._post("/api/agent/chat/", run_id=run_id)
            duplicate = self._post("/api/agent/chat/", run_id=run_id)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(first.json()["run_id"], str(run_id))
        self.assertEqual(first.json()["status"], AgentRun.Status.SUCCEEDED)
        self.assertEqual(first.json()["answer"], duplicate.json()["answer"])
        self.assertEqual(first["X-Agent-Run-ID"], str(run_id))
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(AgentRun.objects.count(), 1)
        run = AgentRun.objects.get(run_id=run_id)
        self.assertEqual(list(run.messages.values_list("role", flat=True)), ["user", "agent"])
        self.assertEqual(AgentObservation.objects.filter(agent_run=run).count(), 1)
        self.assertTrue(run.model_accounting["unobserved_model_calls"])
        self.assertFalse(run.model_accounting["complete_cost"])

        detail = self.client.get(f"/api/agent/chat/runs/{run_id}/", HTTP_HOST="localhost")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["result"]["answer"], self._answer().answer)
        self.assertEqual(detail.json()["output_message_id"], run.messages.get(role="agent").id)
        mismatch = self._post("/api/agent/chat/", message="不同的问题", run_id=run_id)
        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(AgentRun.objects.count(), 1)

    def test_stream_close_before_read_drains_and_persists_result(self):
        run_id = uuid.uuid4()
        answer = self._answer().to_dict()
        with patch(
            "apps.agent_api.views.chat.MultiAgentSupervisor.chat_stream",
            return_value=iter([{"type": "trace", "data": "生成中"}, {"type": "response", **answer}]),
        ) as stream:
            response = self._post("/api/agent/chat/stream/", run_id=run_id)
            response.close()  # Simulated disconnect before any SSE bytes are read.
        run = AgentRun.objects.get(run_id=run_id)
        self.assertEqual(run.status, AgentRun.Status.SUCCEEDED)
        self.assertEqual(run.messages.filter(role=Message.Role.AGENT).count(), 1)
        self.assertEqual(stream.call_count, 1)
        detail = self.client.get(f"/api/agent/chat/runs/{run_id}/", HTTP_HOST="localhost")
        self.assertEqual(detail.json()["result"]["answer"], answer["answer"])

    def test_closing_stream_after_response_event_does_not_lose_result(self):
        run_id = uuid.uuid4()
        answer = self._answer().to_dict()
        with patch(
            "apps.agent_api.views.chat.MultiAgentSupervisor.chat_stream",
            return_value=iter([{"type": "trace", "data": "生成中"}, {"type": "response", **answer}]),
        ):
            response = self._post("/api/agent/chat/stream/", run_id=run_id)
            for chunk in response.streaming_content:
                event = json.loads(chunk.decode("utf-8").removeprefix("data: "))
                if event["type"] == "response":
                    break
            response.close()
        run = AgentRun.objects.get(run_id=run_id)
        self.assertEqual(run.status, AgentRun.Status.SUCCEEDED)
        self.assertEqual(run.messages.filter(role=Message.Role.AGENT).count(), 1)

    def test_stream_retry_replays_persisted_result_without_new_execution(self):
        run_id = uuid.uuid4()
        with patch(
            "apps.agent_api.views.chat.MultiAgentSupervisor.chat_stream",
            return_value=iter([{"type": "response", **self._answer().to_dict()}]),
        ) as stream:
            first = self._post("/api/agent/chat/stream/", run_id=run_id)
            first.close()
            second = self._post("/api/agent/chat/stream/", run_id=run_id)
        replay = b"".join(second.streaming_content).decode("utf-8")
        self.assertIn("已核实的模拟回答", replay)
        self.assertEqual(stream.call_count, 1)
        self.assertEqual(Message.objects.filter(agent_run__run_id=run_id).count(), 2)

    def test_response_event_survives_generator_cleanup_error(self):
        run_id = uuid.uuid4()

        def stream_after_result(*_args, **_kwargs):
            yield {"type": "response", **self._answer().to_dict()}
            raise OSError("client transport closed after result")

        with patch("apps.agent_api.views.chat.MultiAgentSupervisor.chat_stream", side_effect=stream_after_result):
            response = self._post("/api/agent/chat/stream/", run_id=run_id)
            body = b"".join(response.streaming_content).decode("utf-8")
        self.assertEqual(AgentRun.objects.get(run_id=run_id).status, AgentRun.Status.SUCCEEDED)
        self.assertIn("已核实的模拟回答", body)

    def test_duplicate_while_model_is_running_returns_same_run_without_new_messages(self):
        run_id = uuid.uuid4()

        def model(*_args, **_kwargs):
            duplicate = self._post("/api/agent/chat/", run_id=run_id)
            self.assertEqual(duplicate.status_code, 202)
            self.assertEqual(duplicate.json()["status"], AgentRun.Status.RUNNING)
            return self._answer()

        with patch("apps.agent_api.views.chat.MultiAgentSupervisor.chat", side_effect=model) as chat:
            first = self._post("/api/agent/chat/", run_id=run_id)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(AgentRun.objects.filter(run_id=run_id).count(), 1)
        self.assertEqual(Message.objects.filter(agent_run__run_id=run_id).count(), 2)

    def test_timeout_is_queryable_failure_and_duplicate_does_not_retry_model(self):
        run_id = uuid.uuid4()
        with patch("apps.agent_api.views.chat.MultiAgentSupervisor.chat", side_effect=TimeoutError) as chat:
            first = self._post("/api/agent/chat/", run_id=run_id)
            duplicate = self._post("/api/agent/chat/", run_id=run_id)
        self.assertEqual(first.status_code, 503)
        self.assertEqual(first.json()["run_id"], str(run_id))
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.json()["status"], AgentRun.Status.FAILED)
        self.assertEqual(chat.call_count, 1)
        run = AgentRun.objects.get(run_id=run_id)
        self.assertEqual(run.error_code, "TimeoutError")
        self.assertEqual(run.messages.count(), 1)
        self.assertEqual(run.observations.get().status, AgentObservation.Status.FAILED)

    def test_stream_timeout_persists_failure_before_error_event(self):
        run_id = uuid.uuid4()
        with patch("apps.agent_api.views.chat.MultiAgentSupervisor.chat_stream", side_effect=TimeoutError):
            response = self._post("/api/agent/chat/stream/", run_id=run_id)
            events = [json.loads(chunk.decode("utf-8").removeprefix("data: ")) for chunk in response.streaming_content]
        self.assertEqual(AgentRun.objects.get(run_id=run_id).status, AgentRun.Status.FAILED)
        self.assertEqual([item["type"] for item in events], ["run", "error", "done"])
        self.assertEqual(events[-1]["status"], AgentRun.Status.FAILED)

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_inner_generation_timeout_propagates_to_run_boundary(self):
        agent = SimpleToolCallingAgent(Path("."))
        agent.llm = object()
        with patch.object(agent, "_invoke_direct_answer_chain", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                agent.chat("你好")
            with self.assertRaises(TimeoutError):
                list(agent.chat_stream("你好"))

    def test_pending_cancel_is_immediate_and_running_cancel_is_cooperative(self):
        pending = self._owned_run()
        response = self.client.post(f"/api/agent/chat/runs/{pending.run_id}/cancel/", HTTP_HOST="localhost")
        self.assertEqual(response.json()["status"], AgentRun.Status.CANCELLED)
        self.assertFalse(start_run(pending))

        run_id = uuid.uuid4()

        def cancel_during_model(*_args, **_kwargs):
            with model_purpose("direct_answer"):
                FakeListChatModel(responses=["completed after cancel request"]).invoke("private input")
            cancellation = self.client.post(f"/api/agent/chat/runs/{run_id}/cancel/", HTTP_HOST="localhost")
            self.assertEqual(cancellation.json()["status"], AgentRun.Status.RUNNING)
            self.assertTrue(cancellation.json()["cancel_requested"])
            return self._answer()

        with patch("apps.agent_api.views.chat.MultiAgentSupervisor.chat", side_effect=cancel_during_model):
            response = self._post("/api/agent/chat/", run_id=run_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], AgentRun.Status.CANCELLED)
        self.assertEqual(AgentRun.objects.get(run_id=run_id).messages.count(), 1)
        self.assertEqual(AgentRun.objects.get(run_id=run_id).model_accounting["call_count"], 1)

    @override_settings(AGENT_CHAT_RUN_STALE_SECONDS=10)
    def test_stale_running_run_is_marked_interrupted_and_late_result_is_rejected(self):
        run = self._owned_run(AgentRun.Status.RUNNING)
        AgentRun.objects.filter(pk=run.pk).update(updated_at=timezone.now() - timedelta(seconds=30))
        result = self.client.get(f"/api/agent/chat/runs/{run.run_id}/", HTTP_HOST="localhost")
        self.assertEqual(result.json()["status"], AgentRun.Status.FAILED)
        self.assertEqual(result.json()["error_code"], "interrupted")
        self.assertFalse(finish_run(run, self._answer().to_dict(), 1))
        self.assertEqual(run.messages.filter(role=Message.Role.AGENT).count(), 0)
        self.assertEqual(run.observations.count(), 1)

    @override_settings(AGENT_CHAT_RUN_STALE_SECONDS=10)
    def test_stale_pending_and_cancel_requested_runs_become_terminal(self):
        pending = self._owned_run()
        cancelling = self._owned_run(AgentRun.Status.RUNNING)
        AgentRun.objects.filter(pk=pending.pk).update(updated_at=timezone.now() - timedelta(seconds=30))
        AgentRun.objects.filter(pk=cancelling.pk).update(
            cancel_requested=True, updated_at=timezone.now() - timedelta(seconds=30)
        )
        pending_result = self.client.get(f"/api/agent/chat/runs/{pending.run_id}/", HTTP_HOST="localhost")
        cancelled_result = self.client.get(f"/api/agent/chat/runs/{cancelling.run_id}/", HTTP_HOST="localhost")
        self.assertEqual(pending_result.json()["status"], AgentRun.Status.FAILED)
        self.assertEqual(cancelled_result.json()["status"], AgentRun.Status.CANCELLED)
        self.assertEqual(pending.observations.count(), 1)
        self.assertEqual(cancelling.observations.count(), 0)

    @override_settings(AGENT_SECURITY_ENFORCED=True)
    def test_run_lookup_and_cancel_check_owner_workspace_and_role(self):
        for run in (
            self._owned_run(owner="another-user"),
            self._owned_run(workspace="another-workspace"),
        ):
            self.assertEqual(
                self.client.get(f"/api/agent/chat/runs/{run.run_id}/", HTTP_HOST="localhost").status_code, 404
            )
            self.assertEqual(
                self.client.post(f"/api/agent/chat/runs/{run.run_id}/cancel/", HTTP_HOST="localhost").status_code,
                404,
            )
            self.assertEqual(self._post("/api/agent/chat/", run_id=run.run_id).status_code, 404)

        owned = self._owned_run()
        self.authenticate_test_user(UserProfile.Role.VISITOR)
        self.assertEqual(
            self.client.get(f"/api/agent/chat/runs/{owned.run_id}/", HTTP_HOST="localhost").status_code, 403
        )
        self.assertEqual(
            self.client.post(f"/api/agent/chat/runs/{owned.run_id}/cancel/", HTTP_HOST="localhost").status_code,
            403,
        )

    def test_approval_request_is_not_duplicated_by_same_run_id(self):
        BlogArticle.objects.create(title="Approval target", slug="approval-target", content="body")
        run_id = uuid.uuid4()
        first = self._post("/api/agent/chat/", message="删除博客 Approval target", run_id=run_id)
        second = self._post("/api/agent/chat/", message="删除博客 Approval target", run_id=run_id)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.json()["approval"]["id"], second.json()["approval"]["id"])
        self.assertEqual(ApprovalRequest.objects.count(), 1)
        self.assertEqual(Message.objects.filter(agent_run__run_id=run_id).count(), 2)
