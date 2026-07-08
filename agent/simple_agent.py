from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from .tools import SafeCalculator, ToolResult, search_knowledge


Route = Literal["retrieve", "direct"]
TokenUsage = dict[str, int]


@dataclass(frozen=True)
class SourceCitation:
    document_id: int
    document_title: str
    chunk_id: int
    chunk_index: int
    score: float
    content: str


class AgentState(TypedDict, total=False):
    message: str
    route: Route
    query: str
    rewritten_query: str
    rewrite_count: int
    answer: str
    tool_calls: list[ToolResult]
    sources: list[SourceCitation]
    trace: list[str]
    token_usage: TokenUsage


@dataclass(frozen=True)
class AgentResponse:
    answer: str
    tool_calls: list[ToolResult]
    sources: list[SourceCitation]
    trace: list[str]
    route: str
    token_usage: TokenUsage

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "tool_calls": [asdict(call) for call in self.tool_calls],
            "sources": [asdict(source) for source in self.sources],
            "trace": self.trace,
            "route": self.route,
            "token_usage": self.token_usage,
        }


class SimpleToolCallingAgent:
    """LangGraph Agentic RAG workflow for direct chat and knowledge-grounded answers."""

    min_relevance_score = 0.12
    max_rewrites = 1

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.llm = self._build_llm()
        self.graph = self._build_graph()

    def chat(self, message: str) -> AgentResponse:
        message = message.strip()
        initial_state: AgentState = {
            "message": message,
            "query": message,
            "rewrite_count": 0,
            "tool_calls": [],
            "sources": [],
            "trace": ["收到用户输入", "进入 Agentic RAG StateGraph"],
            "token_usage": self._empty_token_usage(),
        }

        try:
            final_state = self.graph.invoke(initial_state)
            return AgentResponse(
                answer=final_state.get("answer", ""),
                tool_calls=final_state.get("tool_calls", []),
                sources=final_state.get("sources", []),
                trace=final_state.get("trace", []),
                route=final_state.get("route", "direct"),
                token_usage=final_state.get("token_usage", self._empty_token_usage()),
            )
        except Exception as exc:
            fallback = self._fallback_chat(message)
            return AgentResponse(
                answer=fallback.answer,
                tool_calls=fallback.tool_calls,
                sources=fallback.sources,
                trace=[*initial_state["trace"], f"工作流异常：{exc}", *fallback.trace],
                route=fallback.route,
                token_usage=fallback.token_usage,
            )

    def _build_llm(self) -> ChatOpenAI | None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None

        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=api_key,
            base_url=self._normalized_openai_base_url(),
            temperature=0,
        )

    def _normalized_openai_base_url(self) -> str:
        base_url = os.getenv("OPENAI_BASE_URL", "https://poloai.top/v1/")
        if base_url.startswith("https//"):
            return base_url.replace("https//", "https://", 1)
        if base_url.startswith("http//"):
            return base_url.replace("http//", "http://", 1)
        return base_url

    def _build_graph(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("query_analyzer", self._query_analyzer)
        workflow.add_node("retrieve", self._retrieve)
        workflow.add_node("grade_documents", self._grade_documents)
        workflow.add_node("rewrite_query", self._rewrite_query)
        workflow.add_node("generate", self._generate)
        workflow.add_node("cite_sources", self._cite_sources)

        workflow.set_entry_point("query_analyzer")
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
        route: Route = "retrieve" if self._needs_tool_or_project_context(message) else "direct"
        return {
            **state,
            "route": route,
            "query": message,
            "trace": [*state.get("trace", []), f"query_analyzer -> {route}"],
        }

    def _route_after_query_analyzer(self, state: AgentState) -> Route:
        return state.get("route", "direct")

    def _retrieve(self, state: AgentState) -> AgentState:
        message = state["message"]
        query = state.get("rewritten_query") or state.get("query") or message

        special_tool = self._run_required_non_rag_tool(message)
        if special_tool:
            return {
                **state,
                "tool_calls": [special_tool],
                "sources": [],
                "trace": [*state.get("trace", []), f"retrieve -> {special_tool.name}"],
            }

        tool_call, sources = self._search_sources(query)
        return {
            **state,
            "tool_calls": [tool_call],
            "sources": sources,
            "trace": [
                *state.get("trace", []),
                f"retrieve -> knowledge_search ({len(sources)} sources)",
            ],
        }

    def _grade_documents(self, state: AgentState) -> AgentState:
        sources = state.get("sources", [])
        best_score = max((source.score for source in sources), default=0.0)
        decision = "generate"
        if not sources or best_score < self.min_relevance_score:
            decision = "rewrite" if state.get("rewrite_count", 0) < self.max_rewrites else "generate"

        return {
            **state,
            "trace": [
                *state.get("trace", []),
                f"grade_documents -> best_score={best_score:.3f}, decision={decision}",
            ],
        }

    def _route_after_grading(self, state: AgentState) -> Literal["rewrite", "generate"]:
        last_trace = state.get("trace", [])[-1] if state.get("trace") else ""
        return "rewrite" if "decision=rewrite" in last_trace else "generate"

    def _rewrite_query(self, state: AgentState) -> AgentState:
        original = state["message"]
        rewritten = self._rewrite_query_text(original)
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
            final_message = self._invoke_agentic_rag_chain(state)
        else:
            final_message = self._invoke_no_source_chain(state)

        token_usage = self._merge_token_usage(
            state.get("token_usage", self._empty_token_usage()),
            self._extract_token_usage(final_message),
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

    def _search_sources(self, query: str) -> tuple[ToolResult, list[SourceCitation]]:
        try:
            from apps.agent_api.rag import format_search_results, search_knowledge_base

            results = search_knowledge_base(query, limit=5)
            sources = [
                SourceCitation(
                    document_id=result.document_id,
                    document_title=result.document_title,
                    chunk_id=result.chunk_id,
                    chunk_index=result.chunk_index,
                    score=result.score,
                    content=result.content,
                )
                for result in results
            ]
            return ToolResult("knowledge_search", query, format_search_results(results)), sources
        except Exception as exc:
            output = search_knowledge(query, self.project_root)
            return ToolResult("knowledge_search", query, f"知识库检索暂时不可用：{exc}\n\n{output}"), []

    def _run_required_non_rag_tool(self, message: str) -> ToolResult | None:
        if re.search(r"\d+\s*[\+\-\*/%]\s*\d+", message):
            expression = re.search(r"[\d\s\+\-\*/%\.\(\)]+", message)
            value = expression.group(0).strip() if expression else message
            return ToolResult("calculator", value, SafeCalculator().run(value))

        lowered = message.lower()
        user_keywords = ["当前用户", "用户资料", "我的项目", "我是谁", "profile"]
        if any(keyword in lowered for keyword in user_keywords):
            output = (
                "当前用户正在构建企业知识智能体平台 + 个人博客智能体系统；"
                "技术路线是 Vue 3 + Django + LangChain/LangGraph + RAG + MCP。"
            )
            return ToolResult("current_user_profile", message, output)

        return None

    def _rewrite_query_text(self, message: str) -> str:
        if self.llm is None:
            return f"{message} 相关定义 背景 方法 结论"

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "你是 RAG 检索查询改写器。请把用户问题改写成适合知识库检索的短查询，"
                        "保留关键词、实体、技术术语，不要回答问题。"
                    ),
                ),
                ("human", "{message}"),
            ]
        )
        rewritten_message = (prompt | self.llm).invoke({"message": message})
        return str(rewritten_message.content).strip() or f"{message} 相关资料"

    def _invoke_agentic_rag_chain(self, state: AgentState) -> BaseMessage:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "你是企业知识库 Agentic RAG 助手。请优先依据给定来源回答。"
                        "回答中使用 [1]、[2] 这样的编号引用来源。"
                        "如果来源不足以支持结论，要明确说明“不知道”或“当前资料不足”，不要编造。"
                    ),
                ),
                (
                    "human",
                    "用户问题：{message}\n\n检索查询：{query}\n\n引用来源：\n{source_context}\n\n请生成带引用编号的答案。",
                ),
            ]
        )
        return (prompt | self.llm).invoke(
            {
                "message": state["message"],
                "query": state.get("rewritten_query") or state.get("query") or state["message"],
                "source_context": self._format_source_context(state.get("sources", [])),
            }
        )

    def _invoke_no_source_chain(self, state: AgentState) -> BaseMessage:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "你是企业知识库 Agentic RAG 助手。当前检索没有找到明确相关来源。"
                        "请先说明当前知识库没有找到足够依据；如果可以基于通用知识给出方向，"
                        "需要明确标注这是补充说明，不是来自知识库。"
                    ),
                ),
                ("human", "{message}"),
            ]
        )
        return (prompt | self.llm).invoke({"message": state["message"]})

    def _invoke_direct_answer_chain(self, message: str) -> BaseMessage:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "你是企业知识智能体平台的通用助手。普通知识、创意写作、闲聊、解释概念、"
                        "开放问题都直接回答。不要说数据库没有内容，也不要返回固定模板。"
                    ),
                ),
                ("human", "{message}"),
            ]
        )
        return (prompt | self.llm).invoke({"message": message})

    def _needs_tool_or_project_context(self, message: str) -> bool:
        lowered = message.lower()
        if re.search(r"\d+\s*[\+\-\*/%]\s*\d+", message):
            return True

        user_keywords = ["当前用户", "用户资料", "我的项目", "我是谁", "profile"]
        if any(keyword in lowered for keyword in user_keywords):
            return True

        retrieval_keywords = [
            "检索",
            "搜索",
            "查找",
            "查询项目",
            "项目资料",
            "项目文档",
            "本地文档",
            "知识库",
            "上传的文档",
            "文档里",
            "引用",
            "来源",
            "rag",
            "readme",
            "博客草稿",
        ]
        return any(keyword in lowered for keyword in retrieval_keywords)

    def _format_source_context(self, sources: list[SourceCitation]) -> str:
        if not sources:
            return "没有检索到明确来源。"
        return "\n\n".join(
            (
                f"[{index}] 文档：{source.document_title}\n"
                f"chunk_id：{source.chunk_id}\n"
                f"相似度：{source.score:.3f}\n"
                f"内容：{source.content}"
            )
            for index, source in enumerate(sources, start=1)
        )

    def _extract_token_usage(self, message: BaseMessage) -> TokenUsage:
        usage = getattr(message, "usage_metadata", None)
        if usage:
            return {
                "prompt_tokens": int(usage.get("input_tokens", 0)),
                "completion_tokens": int(usage.get("output_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)),
            }

        response_metadata = getattr(message, "response_metadata", {}) or {}
        token_usage = response_metadata.get("token_usage") or {}
        return {
            "prompt_tokens": int(token_usage.get("prompt_tokens", 0)),
            "completion_tokens": int(token_usage.get("completion_tokens", 0)),
            "total_tokens": int(token_usage.get("total_tokens", 0)),
        }

    def _merge_token_usage(self, left: TokenUsage, right: TokenUsage) -> TokenUsage:
        return {
            "prompt_tokens": left.get("prompt_tokens", 0) + right.get("prompt_tokens", 0),
            "completion_tokens": left.get("completion_tokens", 0) + right.get("completion_tokens", 0),
            "total_tokens": left.get("total_tokens", 0) + right.get("total_tokens", 0),
        }

    def _empty_token_usage(self) -> TokenUsage:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def _fallback_chat(self, message: str) -> AgentResponse:
        empty_usage = self._empty_token_usage()
        if re.search(r"\d+\s*[\+\-\*/%]\s*\d+", message):
            expression = re.search(r"[\d\s\+\-\*/%\.\(\)]+", message)
            value = expression.group(0).strip() if expression else message
            output = SafeCalculator().run(value)
            return AgentResponse(
                answer=f"我调用了计算器工具，结果是：{output}",
                tool_calls=[ToolResult("calculator", value, output)],
                sources=[],
                trace=["本地兜底：calculator"],
                route="retrieve",
                token_usage=empty_usage,
            )

        if self._needs_tool_or_project_context(message):
            tool_call, sources = self._search_sources(message)
            if sources:
                answer = f"当前模型服务不可用，我先返回检索来源。请展开引用来源查看依据。\n\n{tool_call.output}"
            else:
                answer = "当前模型服务不可用，且知识库没有检索到明确来源。"
            return AgentResponse(
                answer=answer,
                tool_calls=[tool_call],
                sources=sources,
                trace=["本地兜底：knowledge_search"],
                route="retrieve",
                token_usage=empty_usage,
            )

        return AgentResponse(
            answer=(
                "这个问题应该由大模型直接回答，但当前模型服务暂时不可用。"
                "请检查 OPENAI_API_KEY、OPENAI_BASE_URL 和网络后重试。"
            ),
            tool_calls=[],
            sources=[],
            trace=["本地兜底：direct_model_unavailable"],
            route="direct",
            token_usage=empty_usage,
        )
