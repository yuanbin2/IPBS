"""LangGraph 驱动的 Agentic RAG 实现。

状态图负责判断是否检索、检索结果是否足够、是否需要改写查询，
并在最终回答中保留来源和 token 统计。

本文件只保留图编排与节点实现；类型（``agent_types``）、查询重写
（``query_rewriting``）、纯文本帮助函数（``agent_text``）、提示词
（``rag_prompts``）与 LLM/token 管道（``llm_support``）已拆到独立模块。
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path

try:
    from django.conf import settings

    if (
        settings.configured
        and settings.DEBUG
        and os.getenv("AGENT_ENABLE_LANGSMITH", "").lower()
        not in {
            "1",
            "true",
            "yes",
        }
    ):
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        os.environ["LANGSMITH_TRACING"] = "false"
except Exception:
    pass

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, StateGraph

from . import agent_text, internet_answer, query_rewriting, rag_tools
from .agent_types import (
    AgentResponse,
    AgentState,
    ConversationHistory,
    GradingDecision,
    Route,
    SourceCitation,  # noqa: F401 — 再导出：multi_agent 等模块沿用 agent.simple_agent 的导入路径
    TokenUsage,
)
from .llm_support import (
    build_openai_chat,
    empty_token_usage,
    extract_token_usage,
    merge_token_usage,
    normalized_openai_base_url,
)
from .rag_prompts import (
    AGENTIC_RAG_PROMPT,
    DIRECT_ANSWER_PROMPT,
    NO_SOURCE_PROMPT,
    QUERY_EXPANSION_PROMPT,
)
from .tools import ToolResult


class SimpleToolCallingAgent:
    """LangGraph Agentic RAG workflow for direct chat and knowledge-grounded answers."""

    min_relevance_score = 0.12
    max_rewrites = 1

    def __init__(self, project_root: Path, workspace_key: str = "default"):
        self.project_root = project_root
        self.workspace_key = workspace_key
        self.llm = self._build_llm()
        self.graph = self._build_graph()

    def _initial_state(self, message: str, retrieval_query: str) -> AgentState:
        """chat/chat_stream 共用的图初始状态；trace 记录查询消解结果。"""
        context_trace = [f"context_query_rewrite -> {retrieval_query}"] if retrieval_query != message else []
        return {
            "message": message,
            "query": retrieval_query,
            "rewrite_count": 0,
            "tool_calls": [],
            "sources": [],
            "trace": ["收到用户输入", *context_trace, "进入 Agentic RAG StateGraph"],
            "token_usage": empty_token_usage(),
        }

    def chat(
        self,
        message: str,
        history: ConversationHistory | None = None,
    ) -> AgentResponse:
        message = message.strip()
        history = history or []
        # 先结合历史消解代词，再进入检索图；否则“他/这个项目”等
        # 追问会丢失上一轮的人名或主题。
        retrieval_query = self.rewrite_retrieval_query(message, history)
        initial_state = self._initial_state(message, retrieval_query)

        try:
            final_state = self.graph.invoke(initial_state)
            return AgentResponse(
                answer=final_state.get("answer", ""),
                tool_calls=final_state.get("tool_calls", []),
                sources=final_state.get("sources", []),
                trace=final_state.get("trace", []),
                route=final_state.get("route", "direct"),
                token_usage=final_state.get("token_usage", empty_token_usage()),
            )
        except Exception as exc:
            fallback = self._fallback_chat(message, retrieval_query=retrieval_query)
            return AgentResponse(
                answer=fallback.answer,
                tool_calls=fallback.tool_calls,
                sources=fallback.sources,
                trace=[*initial_state["trace"], f"工作流异常：{type(exc).__name__}", *fallback.trace],
                route=fallback.route,
                token_usage=fallback.token_usage,
            )

    def chat_stream(
        self,
        message: str,
        history: ConversationHistory | None = None,
    ) -> Iterator[dict]:
        """Yield trace updates as the graph processes each node, then the final response.

        Each yield is a dict with a "type" key:
        - {"type": "trace", "data": "trace entry text"}
        - {"type": "response", "answer": ..., "tool_calls": ..., ...}
        """
        message = message.strip()
        history = history or []
        retrieval_query = self.rewrite_retrieval_query(message, history)
        initial_state = self._initial_state(message, retrieval_query)

        # Emit the initial trace entries
        for trace_entry in initial_state["trace"]:
            yield {"type": "trace", "data": trace_entry}

        seen_trace_count = len(initial_state["trace"])
        final_state = None

        try:
            for step in self.graph.stream(initial_state, stream_mode="updates"):
                for state_update in step.values():
                    traces = state_update.get("trace", [])
                    for trace_entry in traces[seen_trace_count:]:
                        yield {"type": "trace", "data": trace_entry}
                    seen_trace_count = len(traces)
                    # Keep track of the latest state for the final response
                    final_state = {**(final_state or {}), **state_update}

            if final_state:
                yield {
                    "type": "response",
                    "answer": final_state.get("answer", ""),
                    "tool_calls": [asdict(call) for call in final_state.get("tool_calls", [])],
                    "sources": [asdict(source) for source in final_state.get("sources", [])],
                    "trace": final_state.get("trace", []),
                    "route": final_state.get("route", "direct"),
                    "token_usage": final_state.get("token_usage", empty_token_usage()),
                }
            else:
                # Fallback if no steps were executed
                fallback = self._fallback_chat(message, retrieval_query=retrieval_query)
                yield {
                    "type": "response",
                    "answer": fallback.answer,
                    "tool_calls": [asdict(call) for call in fallback.tool_calls],
                    "sources": [asdict(source) for source in fallback.sources],
                    "trace": [*initial_state["trace"], *fallback.trace],
                    "route": fallback.route,
                    "token_usage": fallback.token_usage,
                }
        except Exception as exc:
            fallback = self._fallback_chat(message, retrieval_query=retrieval_query)
            yield {
                "type": "response",
                "answer": fallback.answer,
                "tool_calls": [asdict(call) for call in fallback.tool_calls],
                "sources": [asdict(source) for source in fallback.sources],
                "trace": [*initial_state["trace"], f"工作流异常：{type(exc).__name__}", *fallback.trace],
                "route": fallback.route,
                "token_usage": fallback.token_usage,
            }

    def direct_chat(self, message: str, history: ConversationHistory | None = None) -> AgentResponse:
        """Answer from the model's general knowledge without retrieval."""
        message = message.strip()
        if self.llm is None:
            return self._fallback_chat(message)
        try:
            final_message = self._invoke_direct_answer_chain(message, history or [])
            return AgentResponse(
                answer=str(final_message.content),
                tool_calls=[],
                sources=[],
                trace=["direct_model -> completed"],
                route="direct",
                token_usage=extract_token_usage(final_message),
            )
        except Exception as exc:
            fallback = self._fallback_chat(message)
            return AgentResponse(
                answer=fallback.answer,
                tool_calls=fallback.tool_calls,
                sources=fallback.sources,
                trace=[f"direct_model -> failed: {type(exc).__name__}", *fallback.trace],
                route=fallback.route,
                token_usage=fallback.token_usage,
            )

    def answer_with_external_context(
        self,
        message: str,
        context: str,
        tool_call: ToolResult,
        history: ConversationHistory | None = None,
    ) -> AgentResponse:
        """Synthesize an answer from explicitly enabled, untrusted web context."""
        return internet_answer.answer_with_external_context(self.llm, message, context, tool_call, history)

    def rewrite_web_search_query(
        self,
        message: str,
        history: ConversationHistory | None = None,
    ) -> str:
        """Turn a contextual follow-up into a standalone web-search query."""
        return query_rewriting.rewrite_web_search_query(self.llm, message, history)

    def rewrite_retrieval_query(
        self,
        message: str,
        history: ConversationHistory | None = None,
    ) -> str:
        """Resolve follow-up references before searching the private knowledge base."""
        return query_rewriting.rewrite_retrieval_query(self.llm, message, history)

    def _build_llm(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        return build_openai_chat(
            api_key=api_key,
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            base_url=self._normalized_openai_base_url(),
            temperature=0,
        )

    def _normalized_openai_base_url(self) -> str:
        return normalized_openai_base_url("https://poloai.top/v1/")

    def _build_graph(self):
        """构建“分析→检索→评分→改写→生成→引用”的有限状态图。"""
        workflow = StateGraph(AgentState)
        workflow.add_node("query_analyzer", self._query_analyzer)
        workflow.add_node("retrieve", self._retrieve)
        workflow.add_node("grade_documents", self._grade_documents)
        workflow.add_node("rewrite_query", self._rewrite_query)
        workflow.add_node("generate", self._generate)
        workflow.add_node("cite_sources", self._cite_sources)

        workflow.set_entry_point("query_analyzer")
        # 普通知识问题可直接生成；需要私有知识的问题才进入 RAG，
        # 以减少无意义检索和 embedding 开销。
        workflow.add_conditional_edges(
            "query_analyzer",
            self._route_after_query_analyzer,
            {
                "retrieve": "retrieve",
                "direct": "generate",
            },
        )
        workflow.add_edge("retrieve", "grade_documents")
        workflow.add_conditional_edges(
            "grade_documents",
            self._route_after_grading,
            {
                "rewrite": "rewrite_query",
                "generate": "generate",
            },
        )
        workflow.add_edge("rewrite_query", "retrieve")
        workflow.add_edge("generate", "cite_sources")
        workflow.add_edge("cite_sources", END)
        return workflow.compile()

    def _query_analyzer(self, state: AgentState) -> AgentState:
        message = state["message"]
        # Retrieval-first policy: relevance grading decides whether knowledge
        # context is used or the model falls back to a context-free answer.
        route: Route = "retrieve"
        return {
            **state,
            "route": route,
            # Keep the context-resolved query prepared by chat(). Replacing it
            # with the raw follow-up here would lose entities such as the person
            # referenced by “他/她/它”.
            "query": state.get("query") or message,
            "trace": [*state.get("trace", []), f"query_analyzer -> {route}"],
        }

    def _route_after_query_analyzer(self, state: AgentState) -> Route:
        return state.get("route", "direct")

    def _retrieve(self, state: AgentState) -> AgentState:
        message = state["message"]
        query = state.get("rewritten_query") or state.get("query") or message

        # 计算器等确定性工具比向量检索更可靠，因此优先短路执行。
        special_tool = rag_tools.run_required_non_rag_tool(message)
        if special_tool:
            return {
                **state,
                "tool_calls": [special_tool],
                "sources": [],
                "trace": [*state.get("trace", []), f"retrieve -> {special_tool.name}"],
            }

        expansion_trace = "query_expansion_agent -> skipped for rewritten query"
        if not state.get("rewritten_query"):
            query, expansion_trace = self._expand_query_with_llm(query)

        tool_call, sources = rag_tools.search_sources(
            query, workspace_key=self.workspace_key, project_root=self.project_root
        )
        return {
            **state,
            "tool_calls": [tool_call],
            "sources": sources,
            "trace": [
                *state.get("trace", []),
                expansion_trace,
                f"retrieve -> knowledge_search ({len(sources)} sources)",
            ],
        }

    def _expand_query_with_llm(self, query: str) -> tuple[str, str]:
        """Generate multilingual retrieval aliases without requiring code changes."""
        from apps.agent_api.services.rag import expand_multilingual_query, query_entity_terms

        deterministic = expand_multilingual_query(query)
        if deterministic != query or query_entity_terms(query) or agent_text.is_affiliation_question(query):
            return (
                deterministic,
                "query_expansion_agent -> deterministic entity/intent expansion",
            )

        if self.llm is None:
            return query, "query_expansion_agent -> model unavailable; deterministic fallback"

        try:
            response = (QUERY_EXPANSION_PROMPT | self.llm).invoke({"query": query})
            aliases = re.sub(r"\s+", " ", str(response.content)).strip()
            if not aliases:
                return query, "query_expansion_agent -> empty output; deterministic fallback"
            expanded = f"{query} {aliases}"[:1200]
            return expanded, f"query_expansion_agent -> generated multilingual aliases: {aliases[:240]}"
        except Exception as exc:
            return query, f"query_expansion_agent -> failed ({type(exc).__name__}); deterministic fallback"

    def _grade_documents(self, state: AgentState) -> AgentState:
        sources = state.get("sources", [])
        best_score = max((source.score for source in sources), default=0.0)
        decision = "generate"
        relevant = bool(sources) and best_score >= self.min_relevance_score
        # 低相关结果最多触发一次查询改写，防止状态图无限循环。
        if not relevant:
            decision = "rewrite" if state.get("rewrite_count", 0) < self.max_rewrites else "generate"

        retained_sources = sources
        fallback_trace: list[str] = []
        if not relevant and decision == "generate":
            retained_sources = []
            fallback_trace.append("retrieval_fallback -> no relevant source; direct generation")

        return {
            **state,
            "sources": retained_sources,
            "grading_decision": decision,
            "trace": [
                *state.get("trace", []),
                f"grade_documents -> best_score={best_score:.3f}, decision={decision}",
                *fallback_trace,
            ],
        }

    def _route_after_grading(self, state: AgentState) -> GradingDecision:
        # Routing must depend on structured state. Trace text is for humans and
        # may change due to localization or observability formatting.
        return state.get("grading_decision", "generate")

    def _rewrite_query(self, state: AgentState) -> AgentState:
        # Rewrite the standalone contextual query, not the ambiguous raw
        # follow-up, otherwise a second retrieval pass loses conversation memory.
        original = state.get("query") or state["message"]
        rewritten = rag_tools.rewrite_query_text(self.llm, original)
        rewrite_count = state.get("rewrite_count", 0) + 1
        return {
            **state,
            "rewritten_query": rewritten,
            "rewrite_count": rewrite_count,
            "trace": [*state.get("trace", []), f"rewrite_query -> {rewritten}"],
        }

    def _generate(self, state: AgentState) -> AgentState:
        if self.llm is None:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        if state.get("route") == "direct":
            final_message = self._invoke_direct_answer_chain(state["message"])
        elif state.get("sources"):
            affiliation_answer = agent_text.answer_affiliation_question(state["message"], state.get("sources", []))
            final_message = (
                AIMessage(content=affiliation_answer) if affiliation_answer else self._invoke_agentic_rag_chain(state)
            )
        else:
            final_message = self._invoke_no_source_chain(state)

        token_usage = merge_token_usage(
            state.get("token_usage", empty_token_usage()),
            extract_token_usage(final_message),
        )
        return {
            **state,
            "answer": str(final_message.content),
            "token_usage": token_usage,
            "trace": [*state.get("trace", []), "generate -> completed"],
        }

    def _cite_sources(self, state: AgentState) -> AgentState:
        if state.get("sources"):
            return {
                **state,
                "trace": [*state.get("trace", []), f"cite_sources -> {len(state['sources'])} citations"],
            }
        return {
            **state,
            "trace": [*state.get("trace", []), "cite_sources -> no explicit source"],
        }

    def _invoke_agentic_rag_chain(self, state: AgentState) -> BaseMessage:
        return (AGENTIC_RAG_PROMPT | self.llm).invoke(
            {
                "message": state["message"],
                "query": state.get("rewritten_query") or state.get("query") or state["message"],
                "source_context": agent_text.format_source_context(state.get("sources", [])),
            }
        )

    def _invoke_no_source_chain(self, state: AgentState) -> BaseMessage:
        return (NO_SOURCE_PROMPT | self.llm).invoke({"message": state["message"]})

    def _invoke_direct_answer_chain(
        self,
        message: str,
        history: ConversationHistory | None = None,
    ) -> BaseMessage:
        return (DIRECT_ANSWER_PROMPT | self.llm).invoke(
            {"message": message, "history": query_rewriting.format_history(history or [])}
        )

    def _fallback_chat(
        self,
        message: str,
        retrieval_query: str | None = None,
    ) -> AgentResponse:
        empty_usage = empty_token_usage()
        calculator_call = rag_tools.run_required_non_rag_tool(message)
        if calculator_call is not None and calculator_call.name == "calculator":
            return AgentResponse(
                answer=f"我调用了计算器工具，结果是：{calculator_call.output}",
                tool_calls=[calculator_call],
                sources=[],
                trace=["本地兜底：calculator"],
                route="retrieve",
                token_usage=empty_usage,
            )

        tool_call, sources = rag_tools.search_sources(
            retrieval_query or message, workspace_key=self.workspace_key, project_root=self.project_root
        )
        best_score = max((source.score for source in sources), default=0.0)
        relevant_sources = sources if best_score >= self.min_relevance_score else []
        answer = agent_text.build_grounded_fallback_answer(message, tool_call, relevant_sources)
        fallback_trace = ["本地兜底：knowledge_search"]
        if not relevant_sources:
            fallback_trace.append("retrieval_fallback -> no relevant source; direct generation")
        return AgentResponse(
            answer=answer,
            tool_calls=[tool_call],
            sources=relevant_sources,
            trace=fallback_trace,
            route="retrieve",
            token_usage=empty_usage,
        )

    def _empty_token_usage(self) -> TokenUsage:
        return empty_token_usage()
