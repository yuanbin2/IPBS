from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from .tools import SafeCalculator, ToolResult, build_langchain_tools, search_knowledge


Route = Literal["retrieve", "direct"]
TokenUsage = dict[str, int]


class AgentState(TypedDict, total=False):
    message: str
    route: Route
    messages: list[Any]
    answer: str
    tool_calls: list[ToolResult]
    trace: list[str]
    token_usage: TokenUsage


@dataclass(frozen=True)
class AgentResponse:
    answer: str
    tool_calls: list[ToolResult]
    trace: list[str]
    route: str
    token_usage: TokenUsage

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "tool_calls": [asdict(call) for call in self.tool_calls],
            "trace": self.trace,
            "route": self.route,
            "token_usage": self.token_usage,
        }


class SimpleToolCallingAgent:
    """LangGraph workflow for direct chat, tool calling, and RAG context generation."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.tools = build_langchain_tools(project_root)
        self.tools_by_name: dict[str, BaseTool] = {item.name: item for item in self.tools}
        self.llm = self._build_llm()
        self.graph = self._build_graph()

    def chat(self, message: str) -> AgentResponse:
        message = message.strip()
        initial_state: AgentState = {
            "message": message,
            "tool_calls": [],
            "trace": ["收到用户输入", "进入 LangGraph StateGraph"],
            "token_usage": self._empty_token_usage(),
        }

        try:
            final_state = self.graph.invoke(initial_state)
            return AgentResponse(
                answer=final_state.get("answer", ""),
                tool_calls=final_state.get("tool_calls", []),
                trace=final_state.get("trace", []),
                route=final_state.get("route", "direct"),
                token_usage=final_state.get("token_usage", self._empty_token_usage()),
            )
        except Exception as exc:
            fallback = self._fallback_chat(message)
            return AgentResponse(
                answer=fallback.answer,
                tool_calls=fallback.tool_calls,
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
        workflow.add_node("classify_question", self._classify_question)
        workflow.add_node("retrieve_or_direct", self._retrieve_or_direct)
        workflow.add_node("generate_answer", self._generate_answer)
        workflow.add_node("save_history", self._save_history)

        workflow.set_entry_point("classify_question")
        workflow.add_conditional_edges(
            "classify_question",
            self._route_after_classification,
            {
                "retrieve": "retrieve_or_direct",
                "direct": "generate_answer",
            },
        )
        workflow.add_edge("retrieve_or_direct", "generate_answer")
        workflow.add_edge("generate_answer", "save_history")
        workflow.add_edge("save_history", END)
        return workflow.compile()

    def _classify_question(self, state: AgentState) -> AgentState:
        message = state["message"]
        route: Route = "retrieve" if self._needs_tool_or_project_context(message) else "direct"
        return {
            **state,
            "route": route,
            "trace": [*state.get("trace", []), f"classify_question -> {route}"],
        }

    def _route_after_classification(self, state: AgentState) -> Route:
        return state.get("route", "direct")

    def _retrieve_or_direct(self, state: AgentState) -> AgentState:
        if self.llm is None:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        message = state["message"]
        tool_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "你是企业知识智能体平台的工具调度节点。当前问题已经需要工具或项目上下文。"
                        "请从 knowledge_search、current_user_profile、calculator 中选择工具。"
                        "计算问题必须调用 calculator；用户画像问题调用 current_user_profile；"
                        "文档、知识库、项目资料、RAG、博客草稿等问题调用 knowledge_search。"
                    ),
                ),
                ("human", "{message}"),
            ]
        )
        tool_chain = tool_prompt | self.llm.bind_tools(self.tools)
        prompt_value = tool_prompt.invoke({"message": message})
        messages = prompt_value.to_messages()
        ai_message = tool_chain.invoke({"message": message})
        token_usage = self._merge_token_usage(
            state.get("token_usage", self._empty_token_usage()),
            self._extract_token_usage(ai_message),
        )
        tool_calls: list[ToolResult] = []

        messages.append(ai_message)
        for call in ai_message.tool_calls:
            tool_name = call["name"]
            args = call.get("args", {})
            tool_input = self._stringify_tool_args(args)
            output = self.tools_by_name[tool_name].invoke(args)
            tool_calls.append(ToolResult(tool_name, tool_input, str(output)))
            messages.append(ToolMessage(content=str(output), tool_call_id=call["id"]))

        if not tool_calls and ai_message.content:
            return {
                **state,
                "messages": messages,
                "answer": str(ai_message.content),
                "tool_calls": [],
                "token_usage": token_usage,
                "trace": [*state.get("trace", []), "retrieve_or_direct -> 模型未调用工具，保留模型直接回答"],
            }

        return {
            **state,
            "messages": messages,
            "tool_calls": tool_calls,
            "token_usage": token_usage,
            "trace": [
                *state.get("trace", []),
                f"retrieve_or_direct -> {', '.join(call.name for call in tool_calls)}",
            ],
        }

    def _generate_answer(self, state: AgentState) -> AgentState:
        if self.llm is None:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        if state.get("answer") and not state.get("tool_calls"):
            return {
                **state,
                "trace": [*state.get("trace", []), "generate_answer -> 使用已有模型直接回答"],
            }

        if state.get("tool_calls"):
            final_message = self._invoke_rag_answer_chain(state)
            answer = str(final_message.content)
        elif state.get("messages"):
            final_prompt = ChatPromptTemplate.from_messages([MessagesPlaceholder("messages")])
            final_message = (final_prompt | self.llm).invoke({"messages": state["messages"]})
            answer = str(final_message.content)
        else:
            final_message = self._invoke_direct_answer_chain(state["message"])
            answer = str(final_message.content)

        token_usage = self._merge_token_usage(
            state.get("token_usage", self._empty_token_usage()),
            self._extract_token_usage(final_message),
        )
        return {
            **state,
            "answer": answer,
            "token_usage": token_usage,
            "trace": [*state.get("trace", []), "generate_answer -> 完成最终回答"],
        }

    def _invoke_rag_answer_chain(self, state: AgentState) -> BaseMessage:
        final_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "你是企业知识智能体平台的 RAG 回答节点。下面会提供工具检索或计算得到的上下文。"
                        "请优先参考这些上下文，但不要完全受限于上下文。"
                        "如果上下文不足，可以基于通用知识继续回答，并自然说明哪些内容来自上下文、哪些是补充判断。"
                        "不要因为上下文没有命中就说无法回答，也不要只复述工具结果。"
                    ),
                ),
                (
                    "human",
                    "用户问题：{message}\n\n工具上下文：\n{tool_context}\n\n请给出最终回答。",
                ),
            ]
        )
        return (final_prompt | self.llm).invoke(
            {
                "message": state["message"],
                "tool_context": self._format_tool_context(state.get("tool_calls", [])),
            }
        )

    def _invoke_direct_answer_chain(self, message: str) -> BaseMessage:
        direct_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "你是企业知识智能体平台的通用助手。"
                        "这个问题不需要调用工具，请直接用中文回答用户。"
                        "普通知识、创意写作、闲聊、解释概念、开放问题都交给大模型自由回答。"
                        "不要说数据库没有内容，也不要只返回固定模板。"
                    ),
                ),
                ("human", "{message}"),
            ]
        )
        return (direct_prompt | self.llm).invoke({"message": message})

    def _save_history(self, state: AgentState) -> AgentState:
        usage = state.get("token_usage", self._empty_token_usage())
        return {
            **state,
            "trace": [
                *state.get("trace", []),
                f"save_history -> token total {usage.get('total_tokens', 0)}",
                "save_history -> 交给 Django ORM 持久化",
            ],
        }

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
            "rag",
            "readme",
            "博客草稿",
        ]
        return any(keyword in lowered for keyword in retrieval_keywords)

    def _stringify_tool_args(self, args: dict) -> str:
        if not args:
            return ""
        if len(args) == 1:
            return str(next(iter(args.values())))
        return str(args)

    def _format_tool_context(self, tool_calls: list[ToolResult]) -> str:
        if not tool_calls:
            return "没有工具上下文。"
        return "\n\n".join(
            (
                f"工具：{call.name}\n"
                f"输入：{call.input}\n"
                f"输出：{call.output}"
            )
            for call in tool_calls
        )

    def _fallback_chat(self, message: str) -> AgentResponse:
        empty_usage = self._empty_token_usage()
        if re.search(r"\d+\s*[\+\-\*/%]\s*\d+", message):
            expression = re.search(r"[\d\s\+\-\*/%\.\(\)]+", message)
            value = expression.group(0).strip() if expression else message
            output = SafeCalculator().run(value)
            return AgentResponse(
                answer=f"我调用了计算器工具，结果是：{output}",
                tool_calls=[ToolResult("calculator", value, output)],
                trace=["本地兜底：calculator"],
                route="retrieve",
                token_usage=empty_usage,
            )

        if any(keyword in message.lower() for keyword in ["我是谁", "当前用户", "用户资料", "我的项目", "profile"]):
            output = (
                "当前用户正在构建企业知识智能体平台 + 个人博客智能体系统；"
                "技术路线是 Vue 3 + Django + LangChain/LangGraph + RAG + MCP。"
            )
            return AgentResponse(
                answer=f"我读取了当前用户资料：{output}",
                tool_calls=[ToolResult("current_user_profile", message, output)],
                trace=["本地兜底：current_user_profile"],
                route="retrieve",
                token_usage=empty_usage,
            )

        if self._needs_tool_or_project_context(message):
            output = search_knowledge(message, self.project_root)
            return AgentResponse(
                answer=(
                    "当前模型服务不可用，我先返回检索上下文。模型恢复后，这些上下文会作为 prompt 的一部分，"
                    f"再由大模型综合生成最终答案。\n\n{output}"
                ),
                tool_calls=[ToolResult("knowledge_search", message, output)],
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
            trace=["本地兜底：direct_model_unavailable"],
            route="direct",
            token_usage=empty_usage,
        )
