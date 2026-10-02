"""多智能体调度层。

Supervisor 只负责识别意图、执行安全策略并把请求交给专用 Agent；
路由判定在 ``supervisor_routing``，各专用 Agent 的实现在 ``specialized_agents``，
知识检索、博客问答、MCP 工具等具体能力仍由各自模块实现。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, replace
from pathlib import Path

from . import specialized_agents
from .agent_types import (  # noqa: F401 — 类型再导出，保持既有导入路径
    MultiAgentResponse,
    SpecializedAgentName,
    SupervisorDecision,
)
from .security import detect_sensitive_input, redact_sensitive_output
from .simple_agent import SimpleToolCallingAgent
from .supervisor_routing import (
    decide,
    decision,
    is_mcp_request,
    is_system_stack_question,
    routing_message,
    select_mcp_tool_name,
)


def _safe_response(response: MultiAgentResponse) -> MultiAgentResponse:
    """Redact secrets in every exposed channel, including tool output and citations."""
    changed = False

    def clean(value: str) -> str:
        nonlocal changed
        result, redacted = redact_sensitive_output(value)
        changed |= redacted
        return result

    answer = clean(response.answer)
    tool_calls = [replace(call, input=clean(call.input), output=clean(call.output)) for call in response.tool_calls]
    sources = [
        replace(source, document_title=clean(source.document_title), content=clean(source.content))
        for source in response.sources
    ]
    trace = [clean(item) for item in response.trace]
    if changed and "security_filter -> output redacted" not in trace:
        trace.append("security_filter -> output redacted")
    return replace(response, answer=answer, tool_calls=tool_calls, sources=sources, trace=trace)


def _safe_stream_event(event: dict) -> dict:
    """Apply the same redaction to serialized SSE responses from all routes."""
    changed = False

    def clean(value):
        nonlocal changed
        if isinstance(value, str):
            result, redacted = redact_sensitive_output(value)
            changed |= redacted
            return result
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        return value

    safe = clean(event)
    if changed and safe.get("type") == "response" and "security_filter -> output redacted" not in safe.get("trace", []):
        safe["trace"] = [*safe.get("trace", []), "security_filter -> output redacted"]
    return safe


class MultiAgentSupervisor:
    """Supervisor that routes chat requests to specialized enterprise agents."""

    def __init__(self, project_root: Path, workspace_key: str = "default"):
        self.project_root = project_root
        self.workspace_key = workspace_key
        self.rag_agent = SimpleToolCallingAgent(project_root, workspace_key=workspace_key)

    def chat(
        self,
        message: str,
        internet_enabled: bool = False,
        history: list[dict[str, str]] | None = None,
    ) -> MultiAgentResponse:
        message = message.strip()
        history = history or []

        # 安全检查必须在意图路由之前执行，避免敏感请求被普通 RAG
        # 或工具关键词提前命中，从而绕过人工审批。
        sensitive_marker = detect_sensitive_input(message)
        if sensitive_marker:
            response = specialized_agents.run_admin_approval_agent(message)
            return _safe_response(
                MultiAgentResponse(
                    answer=response.answer,
                    tool_calls=response.tool_calls,
                    sources=response.sources,
                    trace=[
                        "security_filter -> sensitive input detected",
                        f"security_filter -> pattern={sensitive_marker}",
                        *response.trace,
                    ],
                    route=response.route,
                    token_usage=response.token_usage,
                    supervisor=decision(
                        "admin_approval_agent",
                        "Admin Approval Agent",
                        "security filter requires human approval",
                        0.97,
                    ),
                )
            )

        # 把最近对话压缩进路由输入，使“他是哪个学校”等追问仍能
        # 继承上一轮实体；真正交给下游 Agent 的 history 仍保留结构化格式。
        route_decision = decide(routing_message(message, history))
        explicit_web_search = is_mcp_request(message) and select_mcp_tool_name(message) == "web_search"
        trace = [
            "supervisor -> received request",
            f"supervisor -> {route_decision.selected_agent} ({route_decision.reason})",
            f"context_memory -> {len(history)} previous messages",
            route_decision.handoff,
        ]

        # 联网必须由用户显式授权：要么打开开关，要么在消息中明确要求
        # “网页搜索/联网搜索”。实际访问仍只通过注册过的 web_search MCP。
        if explicit_web_search or (
            internet_enabled and (not is_mcp_request(message) or select_mcp_tool_name(message) == "web_search")
        ):
            return _safe_response(
                specialized_agents.run_internet_agent(
                    self.rag_agent, self.project_root, self.workspace_key, message, trace, history
                )
            )

        if route_decision.selected_agent == "rag_agent":
            response = self.rag_agent.chat(message, history=history)
            return _safe_response(
                specialized_agents.from_agent_response(response, route_decision, trace, redact_sensitive_output)
            )

        if route_decision.selected_agent == "blog_agent":
            response = specialized_agents.run_blog_agent(self.project_root, message, history)
        elif route_decision.selected_agent == "sql_analysis_agent":
            response = specialized_agents.run_sql_analysis_agent(message, self.workspace_key)
        elif route_decision.selected_agent == "mcp_tool_agent":
            response = specialized_agents.run_mcp_tool_agent(self.project_root, self.workspace_key, message)
        elif route_decision.selected_agent == "review_agent":
            response = specialized_agents.run_review_agent(message, history)
        elif route_decision.selected_agent == "admin_approval_agent":
            response = specialized_agents.run_admin_approval_agent(message)
        else:
            response = specialized_agents.run_writing_agent(self.rag_agent, message, history)

        answer, redacted = redact_sensitive_output(response.answer)
        extra_trace = ["security_filter -> output redacted"] if redacted else []
        return _safe_response(
            MultiAgentResponse(
                answer=answer,
                tool_calls=response.tool_calls,
                sources=response.sources,
                trace=[*trace, *response.trace, *extra_trace],
                route=response.route,
                token_usage=response.token_usage,
                supervisor=route_decision,
            )
        )

    def chat_stream(
        self,
        message: str,
        internet_enabled: bool = False,
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[dict]:
        """Stream trace entries and final response as SSE-compatible dicts.

        Each yield is a dict with a "type" key:
        - {"type": "trace", "data": "trace entry text"}
        - {"type": "response", "answer": ..., "tool_calls": ..., ...}
        - {"type": "error", "detail": "error message"}
        """
        message = message.strip()
        history = history or []

        # Security check
        sensitive_marker = detect_sensitive_input(message)
        if sensitive_marker:
            yield {"type": "trace", "data": "security_filter -> sensitive input detected"}
            yield {"type": "trace", "data": f"security_filter -> pattern={sensitive_marker}"}
            response = specialized_agents.run_admin_approval_agent(message)
            yield _safe_stream_event(
                {
                    "type": "response",
                    "answer": response.answer,
                    "tool_calls": [asdict(call) for call in response.tool_calls],
                    "sources": [asdict(source) for source in response.sources],
                    "trace": response.trace,
                    "route": response.route,
                    "token_usage": response.token_usage,
                    "supervisor": asdict(
                        decision(
                            "admin_approval_agent",
                            "Admin Approval Agent",
                            "security filter requires human approval",
                            0.97,
                        )
                    ),
                }
            )
            return

        # Supervisor routing
        route_decision = decide(routing_message(message, history))
        explicit_web_search = is_mcp_request(message) and select_mcp_tool_name(message) == "web_search"

        base_trace = [
            "supervisor -> received request",
            f"supervisor -> {route_decision.selected_agent} ({route_decision.reason})",
            f"context_memory -> {len(history)} previous messages",
            route_decision.handoff,
        ]
        for trace_entry in base_trace:
            yield {"type": "trace", "data": trace_entry}

        # Internet search path
        if explicit_web_search or (
            internet_enabled and (not is_mcp_request(message) or select_mcp_tool_name(message) == "web_search")
        ):
            yield {"type": "trace", "data": "internet_agent -> starting web search"}
            response = specialized_agents.run_internet_agent(
                self.rag_agent, self.project_root, self.workspace_key, message, base_trace, history
            )
            response = _safe_response(response)
            yield _safe_stream_event(
                {
                    "type": "response",
                    "answer": response.answer,
                    "tool_calls": [asdict(call) for call in response.tool_calls],
                    "sources": [asdict(source) for source in response.sources],
                    "trace": response.trace,
                    "route": response.route,
                    "token_usage": response.token_usage,
                    "supervisor": asdict(response.supervisor),
                }
            )
            return

        # RAG agent — stream LangGraph execution
        if route_decision.selected_agent == "rag_agent":
            seen_trace = set()
            for trace_entry in base_trace:
                seen_trace.add(trace_entry)
            for event in self.rag_agent.chat_stream(message, history=history):
                if event["type"] == "trace":
                    if event["data"] not in seen_trace:
                        seen_trace.add(event["data"])
                        yield _safe_stream_event(event)
                elif event["type"] == "response":
                    answer, redacted = redact_sensitive_output(event["answer"])
                    extra_trace = ["security_filter -> output redacted"] if redacted else []
                    yield _safe_stream_event(
                        {
                            "type": "response",
                            "answer": answer,
                            "tool_calls": event["tool_calls"],
                            "sources": event["sources"],
                            "trace": [*base_trace, *event["trace"], *extra_trace],
                            "route": event["route"],
                            "token_usage": event["token_usage"],
                            "supervisor": asdict(route_decision),
                        }
                    )
            return

        # Other agents — synchronous, yield trace then response
        if route_decision.selected_agent == "blog_agent":
            yield {"type": "trace", "data": "blog_agent -> public blog/resume retrieval completed"}
            response = specialized_agents.run_blog_agent(self.project_root, message, history)
        elif route_decision.selected_agent == "sql_analysis_agent":
            yield {"type": "trace", "data": "sql_analysis_agent -> safe aggregate query completed"}
            response = specialized_agents.run_sql_analysis_agent(message, self.workspace_key)
        elif route_decision.selected_agent == "mcp_tool_agent":
            yield {"type": "trace", "data": "mcp_tool_agent -> executing tool"}
            response = specialized_agents.run_mcp_tool_agent(self.project_root, self.workspace_key, message)
        elif route_decision.selected_agent == "review_agent":
            yield {"type": "trace", "data": "review_agent -> checking previous answer and sources"}
            response = specialized_agents.run_review_agent(message, history)
        elif route_decision.selected_agent == "admin_approval_agent":
            yield {"type": "trace", "data": "admin_approval_agent -> manual approval required"}
            response = specialized_agents.run_admin_approval_agent(message)
        else:
            yield {"type": "trace", "data": "general_llm_agent -> no retrieval"}
            response = specialized_agents.run_writing_agent(self.rag_agent, message, history)

        answer, redacted = redact_sensitive_output(response.answer)
        extra_trace = ["security_filter -> output redacted"] if redacted else []
        yield _safe_stream_event(
            {
                "type": "response",
                "answer": answer,
                "tool_calls": [asdict(call) for call in response.tool_calls],
                "sources": [asdict(source) for source in response.sources],
                "trace": [*base_trace, *response.trace, *extra_trace],
                "route": response.route,
                "token_usage": response.token_usage,
                "supervisor": asdict(route_decision),
            }
        )

    # 路由相关的类方法保留在 Supervisor 上：测试与上层（审批流）通过
    # MultiAgentSupervisor.is_mcp_request / select_mcp_tool_name 调用。
    @classmethod
    def is_mcp_request(cls, message: str) -> bool:
        return is_mcp_request(message)

    @classmethod
    def is_system_stack_question(cls, message: str) -> bool:
        return is_system_stack_question(message)

    @classmethod
    def select_mcp_tool_name(cls, message: str) -> str:
        return select_mcp_tool_name(message)
