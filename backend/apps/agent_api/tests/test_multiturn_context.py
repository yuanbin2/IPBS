"""Bounded multi-turn RAG context and chat endpoint isolation, using mock answers."""

from pathlib import Path
from unittest.mock import patch

from django.test import TestCase
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from agent.agent_types import MultiAgentResponse, SourceCitation, SupervisorDecision
from agent.query_rewriting import (
    fallback_contextual_search_query,
    format_answer_history,
    format_history,
    rewrite_retrieval_query,
)
from agent.simple_agent import SimpleToolCallingAgent
from agent.tools import ToolResult

from ..models import Conversation, Message
from .support import NO_MODEL_ENV, OperatorApiTestCase


class AnswerContextTests(TestCase):
    def test_pronoun_and_cross_turn_comparison_queries_keep_recent_entities(self):
        history = [
            {"role": "user", "content": "检索材料甲的结论"},
            {"role": "agent", "content": "甲的结论", "sources": [{"document_title": "材料甲"}]},
            {"role": "user", "content": "检索材料乙的结论"},
            {"role": "agent", "content": "乙的结论", "sources": [{"document_title": "材料乙"}]},
        ]
        self.assertIn("材料乙", fallback_contextual_search_query("它的依据呢？", history))
        comparison = fallback_contextual_search_query("比较上面两份材料", history)
        self.assertIn("材料甲", comparison)
        self.assertIn("材料乙", comparison)
        self.assertTrue(comparison.endswith("比较上面两份材料"))
        self.assertNotIn("甲结论", comparison)
        incomplete_model = RunnableLambda(lambda _: AIMessage(content="只比较材料乙"))
        self.assertEqual(rewrite_retrieval_query(incomplete_model, "比较上面两份材料", history), comparison)

    def test_long_history_has_bounded_answer_and_retrieval_context(self):
        history = [{"role": "user", "content": "过期私有内容" * 200}]
        history.extend({"role": "agent", "content": f"旧回答{i}" * 300} for i in range(60))
        history.extend(
            [
                {"role": "user", "content": "后续都用三列表格"},
                {
                    "role": "agent",
                    "content": "明白",
                    "sources": [{"document_title": "材料甲", "content": "不应复制的来源正文"}],
                },
            ]
        )
        answer = format_answer_history(history)
        retrieval = format_history(history)
        self.assertLessEqual(len(answer), 4000)
        self.assertLessEqual(len(retrieval), 2400)
        self.assertIn("后续都用三列表格", answer)
        self.assertIn("材料甲", answer)
        self.assertNotIn("不应复制的来源正文", answer)
        self.assertNotIn("过期私有内容", answer)

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_sync_and_stream_rag_generation_receive_same_separate_contexts(self):
        prompts = []

        def answer(prompt):
            prompts.append("\n".join(message.content for message in prompt.to_messages()))
            return AIMessage(content="甲乙比较[1][2]")

        agent = SimpleToolCallingAgent(Path("."))
        agent.llm = RunnableLambda(answer)
        agent.max_rewrites = 0
        history = [
            {"role": "user", "content": "检索材料甲的结论；后续都用三列表格"},
            {
                "role": "agent",
                "content": "甲结论",
                "sources": [{"document_title": "材料甲", "content": "历史来源原文不得复用"}],
            },
            {"role": "user", "content": "检索材料乙的结论"},
            {"role": "agent", "content": "乙结论", "sources": [{"document_title": "材料乙"}]},
        ]
        sources = [
            SourceCitation(1, "材料甲", 1, 0, 0.9, "甲结论有依据"),
            SourceCitation(2, "材料乙", 2, 0, 0.9, "乙结论有依据"),
        ]
        question = "比较上面两份材料，按刚才格式"
        with (
            patch.object(agent, "rewrite_retrieval_query", return_value="材料甲 材料乙 比较结论") as rewrite,
            patch.object(agent, "_expand_query_with_llm", return_value=("材料甲 材料乙 比较结论", "skipped")),
            patch(
                "agent.rag_tools.search_sources", return_value=(ToolResult("knowledge_search", "query", "ok"), sources)
            ) as search,
        ):
            sync = agent.chat(question, history=history)
            stream = [event for event in agent.chat_stream(question, history=history) if event["type"] == "response"][
                -1
            ]
        self.assertEqual(sync.answer, stream["answer"])
        self.assertEqual(sync.route, stream["route"])
        self.assertEqual(sync.sources, sources)
        self.assertEqual(len(prompts), 2)
        self.assertEqual(prompts[0], prompts[1])
        self.assertIn("后续都用三列表格", prompts[0])
        self.assertIn("材料甲", prompts[0])
        self.assertIn("材料乙", prompts[0])
        self.assertIn("检索查询：材料甲 材料乙 比较结论", prompts[0])
        self.assertIn("甲结论有依据", prompts[0])
        self.assertNotIn("历史来源原文不得复用", prompts[0])
        self.assertIn("历史提到但本轮未检索到的材料不得当作已核实依据", prompts[0])
        self.assertEqual(rewrite.call_count, 2)
        self.assertEqual(search.call_count, 2)

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_topic_switch_stays_direct_and_skips_retrieval(self):
        agent = SimpleToolCallingAgent(Path("."))
        agent.llm = object()
        history = [
            {"role": "user", "content": "检索我的材料甲"},
            {"role": "agent", "content": "甲", "sources": [{"document_title": "材料甲"}]},
        ]
        with (
            patch.object(agent, "_invoke_direct_answer_chain", return_value=AIMessage(content="新话题")) as direct,
            patch("agent.rag_tools.search_sources") as search,
        ):
            response = agent.chat("你好，讲个笑话", history=history)
        self.assertEqual(response.route, "direct")
        direct.assert_called_once_with("你好，讲个笑话", history)
        search.assert_not_called()

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_old_answer_is_not_used_as_evidence_when_current_retrieval_is_empty(self):
        model_calls = []
        agent = SimpleToolCallingAgent(Path("."))
        agent.llm = RunnableLambda(lambda prompt: model_calls.append(prompt) or AIMessage(content="错误推断"))
        agent.max_rewrites = 0
        history = [
            {"role": "user", "content": "检索我的文档"},
            {"role": "agent", "content": "秘密代号是 XYZ", "sources": [{"document_title": "旧材料"}]},
        ]
        with (
            patch.object(agent, "rewrite_retrieval_query", return_value="我的文档 代号"),
            patch.object(agent, "_expand_query_with_llm", return_value=("我的文档 代号", "skipped")),
            patch(
                "agent.rag_tools.search_sources", return_value=(ToolResult("knowledge_search", "query", "missing"), [])
            ),
        ):
            response = agent.chat("根据我的文档，确认代号", history=history)
        self.assertEqual(response.route, "retrieve")
        self.assertEqual(response.sources, [])
        self.assertIn("没有找到足够相关", response.answer)
        self.assertNotIn("XYZ", response.answer)
        self.assertEqual(model_calls, [])


class ConversationIsolationTests(OperatorApiTestCase):
    def _seed(self, owner, workspace, content):
        conversation = Conversation.objects.create(title="context", owner_username=owner, workspace_key=workspace)
        Message.objects.create(conversation=conversation, role=Message.Role.USER, content=content)
        Message.objects.create(conversation=conversation, role=Message.Role.AGENT, content="先前回答")
        return conversation

    @staticmethod
    def _response():
        return MultiAgentResponse(
            answer="模拟回答",
            tool_calls=[],
            sources=[],
            trace=[],
            route="direct",
            token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            supervisor=SupervisorDecision("rag_agent", "RAG", "mock", 1.0, "mock"),
        )

    def test_sync_and_stream_only_load_history_from_own_conversation(self):
        owner = self.test_user.username
        sync_conversation = self._seed(owner, "default", "只属于当前会话")
        stream_conversation = self._seed(owner, "default", "只属于当前会话")
        other_conversation = self._seed(owner, "default", "另一会话机密")
        other_user = self._seed("different-user", "default", "其他用户机密")
        other_workspace = self._seed(owner, "different-workspace", "其他工作区机密")
        response = self._response()
        with (
            patch("apps.agent_api.views.chat.MultiAgentSupervisor.chat", return_value=response) as sync_chat,
            patch(
                "apps.agent_api.views.chat.MultiAgentSupervisor.chat_stream",
                return_value=iter([{"type": "response", **response.to_dict()}]),
            ) as stream_chat,
        ):
            sync = self.client.post(
                "/api/agent/chat/",
                {"message": "按刚才格式", "conversation_id": sync_conversation.id},
                content_type="application/json",
                HTTP_HOST="localhost",
            )
            stream = self.client.post(
                "/api/agent/chat/stream/",
                {"message": "按刚才格式", "conversation_id": stream_conversation.id},
                content_type="application/json",
                HTTP_HOST="localhost",
            )
            list(stream.streaming_content)
            self.assertEqual(sync.status_code, 200)
            self.assertEqual(stream.status_code, 200)
            self.assertEqual(sync_chat.call_args.kwargs["history"], stream_chat.call_args.kwargs["history"])
            self.assertEqual(sync_chat.call_args.kwargs["history"][0]["content"], "只属于当前会话")

            for inaccessible in (other_user, other_workspace):
                denied = self.client.post(
                    "/api/agent/chat/",
                    {"message": "继续", "conversation_id": inaccessible.id},
                    content_type="application/json",
                    HTTP_HOST="localhost",
                )
                self.assertEqual(denied.status_code, 404)
            fresh = self.client.post(
                "/api/agent/chat/",
                {"message": "新会话"},
                content_type="application/json",
                HTTP_HOST="localhost",
            )
        self.assertEqual(fresh.status_code, 200)
        self.assertEqual(sync_chat.call_args.kwargs["history"], [])
        self.assertEqual(Message.objects.filter(conversation=other_conversation).count(), 2)
