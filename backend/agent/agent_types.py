"""Agent 层共用的类型别名与数据结构。

状态图节点之间只通过 ``AgentState`` 传递数据，避免节点依赖隐式全局变量。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, TypedDict

from .tools import ToolResult

Route = Literal["retrieve", "direct"]
GradingDecision = Literal["rewrite", "generate"]
TokenUsage = dict[str, int]
ConversationHistory = list[dict[str, str]]

SpecializedAgentName = Literal[
    "rag_agent",
    "blog_agent",
    "sql_analysis_agent",
    "mcp_tool_agent",
    "writing_agent",
    "review_agent",
    "admin_approval_agent",
]


@dataclass(frozen=True)
class SourceCitation:
    document_id: int
    document_title: str
    chunk_id: int
    chunk_index: int
    score: float
    content: str


class AgentState(TypedDict, total=False):
    # 节点之间只通过这份状态传递数据，避免节点依赖隐式全局变量。
    message: str
    history: ConversationHistory
    route: Route
    query: str
    rewritten_query: str
    rewrite_count: int
    grading_decision: GradingDecision
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


@dataclass(frozen=True)
class SupervisorDecision:
    selected_agent: SpecializedAgentName
    display_name: str
    reason: str
    confidence: float
    handoff: str


@dataclass(frozen=True)
class MultiAgentResponse:
    answer: str
    tool_calls: list[ToolResult]
    sources: list[SourceCitation]
    trace: list[str]
    route: str
    token_usage: TokenUsage
    supervisor: SupervisorDecision

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "tool_calls": [asdict(call) for call in self.tool_calls],
            "sources": [asdict(source) for source in self.sources],
            "trace": self.trace,
            "route": self.route,
            "token_usage": self.token_usage,
            "supervisor": asdict(self.supervisor),
        }
