from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .simple_agent import AgentResponse, SimpleToolCallingAgent, SourceCitation, TokenUsage
from .security import detect_sensitive_input, redact_sensitive_output
from .tools import ToolResult


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


class MultiAgentSupervisor:
    """Supervisor that routes chat requests to specialized enterprise agents."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.rag_agent = SimpleToolCallingAgent(project_root)

    def chat(self, message: str) -> MultiAgentResponse:
        message = message.strip()
        sensitive_marker = detect_sensitive_input(message)
        if sensitive_marker:
            response = self._run_admin_approval_agent(message)
            return MultiAgentResponse(
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
                supervisor=self._decision(
                    "admin_approval_agent",
                    "Admin Approval Agent",
                    "security filter requires human approval",
                    0.97,
                ),
            )

        decision = self._decide(message)
        trace = [
            "supervisor -> received request",
            f"supervisor -> {decision.selected_agent} ({decision.reason})",
            decision.handoff,
        ]

        if decision.selected_agent == "rag_agent":
            response = self.rag_agent.chat(message)
            return self._from_agent_response(response, decision, trace)

        if decision.selected_agent == "blog_agent":
            response = self._run_blog_agent(message)
        elif decision.selected_agent == "sql_analysis_agent":
            response = self._run_sql_analysis_agent(message)
        elif decision.selected_agent == "mcp_tool_agent":
            response = self._run_mcp_tool_agent(message)
        elif decision.selected_agent == "review_agent":
            response = self._run_review_agent(message)
        elif decision.selected_agent == "admin_approval_agent":
            response = self._run_admin_approval_agent(message)
        else:
            response = self._run_writing_agent(message)

        answer, redacted = redact_sensitive_output(response.answer)
        extra_trace = ["security_filter -> output redacted"] if redacted else []
        return MultiAgentResponse(
            answer=answer,
            tool_calls=response.tool_calls,
            sources=response.sources,
            trace=[*trace, *response.trace, *extra_trace],
            route=response.route,
            token_usage=response.token_usage,
            supervisor=decision,
        )

    def _from_agent_response(
        self,
        response: AgentResponse,
        decision: SupervisorDecision,
        trace: list[str],
    ) -> MultiAgentResponse:
        answer, redacted = redact_sensitive_output(response.answer)
        extra_trace = ["security_filter -> output redacted"] if redacted else []
        return MultiAgentResponse(
            answer=answer,
            tool_calls=response.tool_calls,
            sources=response.sources,
            trace=[*trace, *response.trace, *extra_trace],
            route=response.route,
            token_usage=response.token_usage,
            supervisor=decision,
        )

    def _decide(self, message: str) -> SupervisorDecision:
        lowered = message.lower()

        if self._contains_any(lowered, ["mcp", "tool", "工具", "git", "仓库", "本地文件", "文件搜索", "网页搜索"]):
            return self._decision(
                "mcp_tool_agent",
                "MCP Tool Agent",
                "request asks to use or inspect external tools",
                0.86,
            )

        if self._contains_any(lowered, ["审批", "发布审核", "删除", "敏感", "权限", "管理员", "admin"]):
            return self._decision(
                "admin_approval_agent",
                "Admin Approval Agent",
                "request needs governance or destructive-action review",
                0.88,
            )

        if self._contains_any(lowered, ["检查", "审查", "review", "是否可靠", "有没有问题", "幻觉", "引用"]):
            return self._decision(
                "review_agent",
                "Review Agent",
                "request asks for answer quality, citation, or risk review",
                0.82,
            )

        if self._contains_any(lowered, ["统计", "多少", "数量", "访问量", "文章数", "文档数", "sql", "数据分析"]):
            return self._decision(
                "sql_analysis_agent",
                "SQL Analysis Agent",
                "request asks for safe platform statistics",
                0.86,
            )

        if self._contains_any(lowered, ["博客", "简历", "个人", "项目经历", "langgraph 项目", "关于我"]):
            return self._decision(
                "blog_agent",
                "Blog Agent",
                "request is about public blog, resume, or project experience",
                0.84,
            )

        if self._contains_any(lowered, ["写", "润色", "总结", "提纲", "标题", "摘要", "改写", "文案"]):
            return self._decision(
                "writing_agent",
                "Writing Agent",
                "request is primarily a writing or drafting task",
                0.78,
            )

        if re.search(r"\d+\s*[\+\-\*/%]\s*\d+", message) or self._contains_any(
            lowered,
            ["知识库", "rag", "检索", "搜索", "文档", "readme", "mcp", "当前用户", "profile"],
        ):
            return self._decision(
                "rag_agent",
                "RAG Agent",
                "request needs tools, retrieval, or project knowledge",
                0.9,
            )

        return self._decision(
            "writing_agent",
            "Writing Agent",
            "general conversation can be handled directly",
            0.62,
        )

    def _decision(
        self,
        selected_agent: SpecializedAgentName,
        display_name: str,
        reason: str,
        confidence: float,
    ) -> SupervisorDecision:
        return SupervisorDecision(
            selected_agent=selected_agent,
            display_name=display_name,
            reason=reason,
            confidence=confidence,
            handoff=f"handoff -> {display_name}",
        )

    def _run_blog_agent(self, message: str) -> MultiAgentResponse:
        from apps.agent_api.blog_agent import PublicBlogAgent

        blog_agent = PublicBlogAgent(self.project_root)
        blog_agent.llm = None
        answer = blog_agent.answer(message)
        tool_calls = [
            ToolResult(
                name="blog_agent_search",
                input=message,
                output=self._format_blog_sources(answer.sources),
            )
        ]
        sources = [
            SourceCitation(
                document_id=0,
                document_title=source.title,
                chunk_id=index,
                chunk_index=index,
                score=source.score,
                content=source.content,
            )
            for index, source in enumerate(answer.sources, start=1)
        ]
        return MultiAgentResponse(
            answer=answer.answer,
            tool_calls=tool_calls,
            sources=sources,
            trace=["blog_agent -> public blog/resume retrieval completed", *answer.trace],
            route="blog_agent",
            token_usage=answer.token_usage,
            supervisor=self._decision("blog_agent", "Blog Agent", "blog route", 1.0),
        )

    def _run_sql_analysis_agent(self, message: str) -> MultiAgentResponse:
        from apps.agent_api.models import BlogArticle, BlogComment, Conversation, Document, KnowledgeBase

        stats = {
            "knowledge_bases": KnowledgeBase.objects.count(),
            "documents": Document.objects.count(),
            "ready_documents": Document.objects.filter(status=Document.Status.READY).count(),
            "published_articles": BlogArticle.objects.filter(status=BlogArticle.Status.PUBLISHED).count(),
            "draft_articles": BlogArticle.objects.filter(status=BlogArticle.Status.DRAFT).count(),
            "comments": BlogComment.objects.count(),
            "conversations": Conversation.objects.count(),
        }
        output = "\n".join(f"- {key}: {value}" for key, value in stats.items())
        answer = (
            "SQL Analysis Agent 已完成一次安全统计，只返回业务聚合指标，不暴露表结构、字段细节或后台敏感信息。\n\n"
            f"{output}"
        )
        return self._plain_response(
            answer=answer,
            tool_call=ToolResult("safe_sql_analytics", message, output),
            trace=["sql_analysis_agent -> safe aggregate query completed"],
            route="sql_analysis_agent",
        )

    def _run_mcp_tool_agent(self, message: str) -> MultiAgentResponse:
        from django.utils import timezone

        from apps.agent_api.models import MCPTool
        from agent.mcp_tools import LocalMCPToolRunner

        lowered = message.lower()
        if self._contains_any(lowered, ["git", "仓库", "提交", "分支"]):
            selected_tool = "git_repo_info"
        elif self._contains_any(lowered, ["统计", "数据库", "数量"]):
            selected_tool = "safe_database_stats"
        elif self._contains_any(lowered, ["网页", "搜索", "web"]):
            selected_tool = "web_search"
        else:
            selected_tool = "local_file_search"

        try:
            registry_item = MCPTool.objects.get(name=selected_tool)
        except MCPTool.DoesNotExist:
            return self._plain_response(
                answer=f"MCP Tool Agent 没有找到注册工具：{selected_tool}",
                tool_call=ToolResult("mcp_registry_lookup", selected_tool, "tool not registered"),
                trace=["mcp_tool_agent -> registry lookup failed"],
                route="mcp_tool_agent",
            )

        if not registry_item.is_enabled:
            return self._plain_response(
                answer=f"MCP 工具「{registry_item.display_name}」当前已禁用，需要管理员在工具注册表中启用后才能调用。",
                tool_call=ToolResult("mcp_registry_lookup", selected_tool, "tool disabled"),
                trace=["mcp_tool_agent -> tool disabled"],
                route="mcp_tool_agent",
            )

        execution = LocalMCPToolRunner(self.project_root).run(selected_tool, message)
        registry_item.last_used_at = timezone.now()
        registry_item.save(update_fields=["last_used_at", "updated_at"])
        answer = (
            f"MCP Tool Agent 调用了「{registry_item.display_name}」。\n\n"
            f"权限范围：{registry_item.permission_scope}\n\n"
            f"{execution.output}"
        )
        return self._plain_response(
            answer=answer,
            tool_call=ToolResult(f"mcp:{selected_tool}", message, execution.output),
            trace=[f"mcp_tool_agent -> {selected_tool}"],
            route="mcp_tool_agent",
        )

    def _run_writing_agent(self, message: str) -> MultiAgentResponse:
        if self._contains_any(message.lower(), ["笑话", "joke", "ц", "瑧璇"]):
            return MultiAgentResponse(
                answer="Writing Agent：当然可以。为什么程序员喜欢深色模式？因为光会吸引 bug。",
                tool_calls=[],
                sources=[],
                trace=["writing_agent -> casual direct answer"],
                route="direct",
                token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                supervisor=self._decision("writing_agent", "Writing Agent", "casual direct answer", 1.0),
            )

        answer = (
            "Writing Agent 接手了这个请求。\n\n"
            "可以从三个层次组织内容：\n"
            "1. 先说明目标和背景，让读者知道为什么要做。\n"
            "2. 再写实现路径，把关键技术选择、取舍和结果讲清楚。\n"
            "3. 最后补上复盘，包括遇到的问题、下一步优化和可迁移经验。\n\n"
            f"针对你的输入：{message}"
        )
        return self._plain_response(
            answer=answer,
            tool_call=ToolResult("writing_outline", message, "generated structured writing guidance"),
            trace=["writing_agent -> outline generated"],
            route="direct",
        )

    def _run_review_agent(self, message: str) -> MultiAgentResponse:
        answer = (
            "Review Agent 已接手。当前审查结论：\n\n"
            "- 优先检查回答是否引用了知识库或博客来源。\n"
            "- 对没有来源支撑的结论，应标记为推断或建议。\n"
            "- 对涉及后台结构、API Key、数据库字段和管理信息的问题，应拒绝或转交 Admin Approval Agent。\n"
            "- 对写作类输出，重点检查是否跑题、是否有明显事实风险。\n\n"
            f"待审查内容：{message}"
        )
        return self._plain_response(
            answer=answer,
            tool_call=ToolResult("answer_review", message, "quality and safety review checklist generated"),
            trace=["review_agent -> quality checklist generated"],
            route="review_agent",
        )

    def _run_admin_approval_agent(self, message: str) -> MultiAgentResponse:
        answer = (
            "Admin Approval Agent 已拦截该请求。\n\n"
            "这个 Agent 只给出审批建议，不直接执行高风险动作。涉及删除、权限、后台配置、API Key、数据库结构、"
            "用户隐私或发布审核的问题，需要明确管理员确认，并保留操作记录。\n\n"
            f"当前请求：{message}\n\n"
            "建议状态：需要人工确认。"
        )
        return self._plain_response(
            answer=answer,
            tool_call=ToolResult("admin_approval", message, "manual approval required"),
            trace=["admin_approval_agent -> manual approval required"],
            route="admin_approval_agent",
        )

    def _plain_response(
        self,
        answer: str,
        tool_call: ToolResult,
        trace: list[str],
        route: str,
    ) -> MultiAgentResponse:
        return MultiAgentResponse(
            answer=answer,
            tool_calls=[tool_call],
            sources=[],
            trace=trace,
            route=route,
            token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            supervisor=self._decision("writing_agent", "Writing Agent", "local response", 1.0),
        )

    def _format_blog_sources(self, sources) -> str:
        if not sources:
            return "No public blog sources found."
        return "\n\n".join(
            f"[{index}] {source.title}\nkind={source.kind}\nscore={source.score:.3f}\n{source.content}"
            for index, source in enumerate(sources, start=1)
        )

    def _contains_any(self, lowered: str, keywords: list[str]) -> bool:
        return any(keyword.lower() in lowered for keyword in keywords)
