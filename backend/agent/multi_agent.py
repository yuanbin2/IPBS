"""多智能体调度层。

Supervisor 只负责识别意图、执行安全策略并把请求交给专用 Agent；
知识检索、博客问答、MCP 工具等具体能力仍由各自模块实现。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Literal

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

        # 把最近对话压缩进路由输入，使“他是哪个学校”等追问仍能
        # 继承上一轮实体；真正交给下游 Agent 的 history 仍保留结构化格式。
        decision = self._decide(self._routing_message(message, history))
        explicit_web_search = self.is_mcp_request(message) and self.select_mcp_tool_name(message) == "web_search"
        trace = [
            "supervisor -> received request",
            f"supervisor -> {decision.selected_agent} ({decision.reason})",
            f"context_memory -> {len(history)} previous messages",
            decision.handoff,
        ]

        # 联网必须由用户显式授权：要么打开开关，要么在消息中明确要求
        # “网页搜索/联网搜索”。实际访问仍只通过注册过的 web_search MCP。
        if explicit_web_search or (
            internet_enabled and (
                not self.is_mcp_request(message) or self.select_mcp_tool_name(message) == "web_search"
            )
        ):
            return self._run_internet_agent(message, trace, history)

        if decision.selected_agent == "rag_agent":
            response = self.rag_agent.chat(message, history=history)
            return self._from_agent_response(response, decision, trace)

        if decision.selected_agent == "blog_agent":
            response = self._run_blog_agent(message, history)
        elif decision.selected_agent == "sql_analysis_agent":
            response = self._run_sql_analysis_agent(message)
        elif decision.selected_agent == "mcp_tool_agent":
            response = self._run_mcp_tool_agent(message)
        elif decision.selected_agent == "review_agent":
            response = self._run_review_agent(message)
        elif decision.selected_agent == "admin_approval_agent":
            response = self._run_admin_approval_agent(message)
        else:
            response = self._run_writing_agent(message, history)

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
            response = self._run_admin_approval_agent(message)
            yield {
                "type": "response",
                "answer": response.answer,
                "tool_calls": [asdict(call) for call in response.tool_calls],
                "sources": [asdict(source) for source in response.sources],
                "trace": response.trace,
                "route": response.route,
                "token_usage": response.token_usage,
                "supervisor": asdict(self._decision(
                    "admin_approval_agent", "Admin Approval Agent",
                    "security filter requires human approval", 0.97,
                )),
            }
            return

        # Supervisor routing
        decision = self._decide(self._routing_message(message, history))
        explicit_web_search = self.is_mcp_request(message) and self.select_mcp_tool_name(message) == "web_search"

        base_trace = [
            "supervisor -> received request",
            f"supervisor -> {decision.selected_agent} ({decision.reason})",
            f"context_memory -> {len(history)} previous messages",
            decision.handoff,
        ]
        for trace_entry in base_trace:
            yield {"type": "trace", "data": trace_entry}

        # Internet search path
        if explicit_web_search or (
            internet_enabled and (
                not self.is_mcp_request(message) or self.select_mcp_tool_name(message) == "web_search"
            )
        ):
            yield {"type": "trace", "data": "internet_agent -> starting web search"}
            response = self._run_internet_agent(message, base_trace, history)
            yield {
                "type": "response",
                "answer": response.answer,
                "tool_calls": [asdict(call) for call in response.tool_calls],
                "sources": [asdict(source) for source in response.sources],
                "trace": [*base_trace, *response.trace],
                "route": response.route,
                "token_usage": response.token_usage,
                "supervisor": asdict(decision),
            }
            return

        # RAG agent — stream LangGraph execution
        if decision.selected_agent == "rag_agent":
            seen_trace = set()
            for trace_entry in base_trace:
                seen_trace.add(trace_entry)
            for event in self.rag_agent.chat_stream(message, history=history):
                if event["type"] == "trace":
                    if event["data"] not in seen_trace:
                        seen_trace.add(event["data"])
                        yield event
                elif event["type"] == "response":
                    answer, redacted = redact_sensitive_output(event["answer"])
                    extra_trace = ["security_filter -> output redacted"] if redacted else []
                    yield {
                        "type": "response",
                        "answer": answer,
                        "tool_calls": event["tool_calls"],
                        "sources": event["sources"],
                        "trace": [*base_trace, *event["trace"], *extra_trace],
                        "route": event["route"],
                        "token_usage": event["token_usage"],
                        "supervisor": asdict(decision),
                    }
            return

        # Other agents — synchronous, yield trace then response
        if decision.selected_agent == "blog_agent":
            yield {"type": "trace", "data": "blog_agent -> public blog/resume retrieval completed"}
            response = self._run_blog_agent(message, history)
        elif decision.selected_agent == "sql_analysis_agent":
            yield {"type": "trace", "data": "sql_analysis_agent -> safe aggregate query completed"}
            response = self._run_sql_analysis_agent(message)
        elif decision.selected_agent == "mcp_tool_agent":
            yield {"type": "trace", "data": "mcp_tool_agent -> executing tool"}
            response = self._run_mcp_tool_agent(message)
        elif decision.selected_agent == "review_agent":
            yield {"type": "trace", "data": "review_agent -> quality checklist generated"}
            response = self._run_review_agent(message)
        elif decision.selected_agent == "admin_approval_agent":
            yield {"type": "trace", "data": "admin_approval_agent -> manual approval required"}
            response = self._run_admin_approval_agent(message)
        else:
            yield {"type": "trace", "data": "general_llm_agent -> no retrieval"}
            response = self._run_writing_agent(message, history)

        answer, redacted = redact_sensitive_output(response.answer)
        extra_trace = ["security_filter -> output redacted"] if redacted else []
        yield {
            "type": "response",
            "answer": answer,
            "tool_calls": [asdict(call) for call in response.tool_calls],
            "sources": [asdict(source) for source in response.sources],
            "trace": [*base_trace, *response.trace, *extra_trace],
            "route": response.route,
            "token_usage": response.token_usage,
            "supervisor": asdict(decision),
        }

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
        """按安全优先级和业务关键词选择专用 Agent。"""
        lowered = message.lower()

        # Governance has priority over business routing. A request such as
        # "删除知识库" must never be consumed by the retrieval keyword below.
        if self._contains_any(lowered, ["审批", "发布审核", "删除", "敏感", "权限", "管理员", "admin"]):
            return self._decision(
                "admin_approval_agent",
                "Admin Approval Agent",
                "request needs governance or destructive-action review",
                0.88,
            )

        if self.is_mcp_request(message):
            return self._decision(
                "mcp_tool_agent",
                "MCP Tool Agent",
                "request maps to a registered MCP capability",
                0.94,
            )

        if self.is_system_stack_question(message):
            return self._decision(
                "blog_agent",
                "System Facts Agent",
                "system technology-stack facts require grounded blog retrieval",
                0.99,
            )

        # The authenticated chat can search private documents uploaded to the
        # current workspace. Resume requests must not be sent to the public-only
        # Blog Agent, otherwise an uploaded CV can never be retrieved.
        if self._contains_any(
            lowered,
            ["简历", "我的文档", "上传的文档", "上传的资料", "知识库文档", "附件"],
        ):
            return self._decision(
                "rag_agent",
                "Private Knowledge RAG Agent",
                "request targets an uploaded private workspace document",
                0.98,
            )

        if self._contains_any(
            lowered,
            ["哪个学校", "哪所学校", "什么学校", "毕业院校", "就读学校", "作者单位", "任职单位", "来自哪里"],
        ):
            return self._decision(
                "rag_agent",
                "Private Knowledge RAG Agent",
                "person affiliation question requires uploaded-document retrieval",
                0.96,
            )

        if self._contains_any(
            lowered,
            ["散射成像", "散射介质", "散斑相关", "散斑", "scattering imaging", "speckle correlation"],
        ):
            return self._decision(
                "rag_agent",
                "Private Knowledge RAG Agent",
                "technical topic matches bilingual uploaded-document retrieval",
                0.95,
            )

        technical_topic_suffixes = (
            "成像",
            "算法",
            "模型",
            "技术",
            "方法",
            "网络",
            "学习",
            "重建",
            "检测",
            "识别",
            "计算",
        )
        compact_topic = re.sub(r"[\s，。？！,.!?]", "", lowered)
        if 2 <= len(compact_topic) <= 24 and any(term in compact_topic for term in technical_topic_suffixes):
            return self._decision(
                "rag_agent",
                "Private Knowledge RAG Agent",
                "short technical topic requires agent-generated multilingual retrieval",
                0.9,
            )

        retrieval_keywords = [
            "数据库",
            "自己的数据库",
            "知识库",
            "资料库",
            "查找",
            "检索",
            "搜索",
            "网络",
            "网上",
            "相关的东西",
            "相关资料",
            "项目相关",
            "成功的",
            "成功案例",
            "依据",
        ]
        if self._contains_any(lowered, retrieval_keywords):
            return self._decision(
                "rag_agent",
                "Private Knowledge RAG Agent",
                "retrieval-first policy searches the current workspace knowledge base",
                0.91,
            )

        if self._contains_any(lowered, ["mcp", "tool", "工具", "git", "仓库", "本地文件", "文件搜索", "网页搜索"]):
            return self._decision(
                "mcp_tool_agent",
                "MCP Tool Agent",
                "request asks to use or inspect external tools",
                0.86,
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

        if self._contains_any(lowered, ["博客", "个人", "项目经历", "langgraph 项目", "关于我"]):
            return self._decision(
                "blog_agent",
                "Blog Agent",
                "request is about public blog, resume, or project experience",
                0.84,
            )

        if self._contains_any(lowered, ["写", "润色", "总结", "提纲", "标题", "摘要", "改写", "文案"]):
            return self._decision(
                "rag_agent",
                "Retrieval-first Writing Agent",
                "writing request must retrieve relevant workspace context before generation",
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
            "rag_agent",
            "Retrieval-first General Agent",
            "ordinary questions search the workspace before model-only generation",
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

    def _run_blog_agent(self, message: str, history: list[dict[str, str]] | None = None) -> MultiAgentResponse:
        from apps.agent_api.services.blog_agent import PublicBlogAgent

        blog_agent = PublicBlogAgent(self.project_root)
        answer = blog_agent.answer(message, history=history or [])
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
            decision=self._decision("sql_analysis_agent", "SQL Analysis Agent", "safe aggregate query", 1.0),
        )

    def _run_mcp_tool_agent(self, message: str) -> MultiAgentResponse:
        from django.utils import timezone

        from apps.agent_api.models import MCPTool
        from agent.mcp_tools import LocalMCPToolRunner

        selected_tool = self.select_mcp_tool_name(message)

        # 数据库中的 MCPTool 是工具白名单和权限来源。即使代码中存在
        # runner，实现未注册、停用或高风险的工具也不能被直接执行。
        try:
            registry_item = MCPTool.objects.get(name=selected_tool, workspace_key=self.workspace_key)
        except MCPTool.DoesNotExist:
            return self._plain_response(
                answer=f"MCP Tool Agent 没有找到注册工具：{selected_tool}",
                tool_call=ToolResult("mcp_registry_lookup", selected_tool, "tool not registered"),
                trace=["mcp_tool_agent -> registry lookup failed"],
                route="mcp_tool_agent",
                decision=self._decision("mcp_tool_agent", "MCP Tool Agent", "registry lookup", 1.0),
            )

        if not registry_item.is_enabled:
            return self._plain_response(
                answer=f"MCP 工具「{registry_item.display_name}」当前已禁用，需要管理员在工具注册表中启用后才能调用。",
                tool_call=ToolResult("mcp_registry_lookup", selected_tool, "tool disabled"),
                trace=["mcp_tool_agent -> tool disabled"],
                route="mcp_tool_agent",
                decision=self._decision("mcp_tool_agent", "MCP Tool Agent", "tool disabled", 1.0),
            )

        if registry_item.requires_approval:
            return self._plain_response(
                answer=f"MCP 工具「{registry_item.display_name}」需要管理员审批，请通过聊天 API 创建审批单后执行。",
                tool_call=ToolResult("mcp_approval_required", message, f"tool={selected_tool}"),
                trace=["mcp_tool_agent -> approval required"],
                route="mcp_tool_agent",
                decision=self._decision("mcp_tool_agent", "MCP Tool Agent", "tool requires approval", 1.0),
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
            decision=self._decision("mcp_tool_agent", "MCP Tool Agent", "tool execution", 1.0),
        )

    @classmethod
    def is_mcp_request(cls, message: str) -> bool:
        lowered = message.lower()
        explicit_mcp = cls._contains_any(lowered, ["mcp", "调用工具", "使用工具", "用工具"])
        explicit_capability = cls._contains_any(
            lowered,
            [
                "网页搜索",
                "网络搜索",
                "网上搜索",
                "联网搜索",
                "web search",
                "在网络中查找",
                "在网络中搜索",
                "在网上查找",
                "在网上搜索",
                "用网络查找",
                "用网络搜索",
                "本地文件",
                "项目文件",
                "文件搜索",
                "代码搜索",
                "git 仓库",
                "git状态",
                "git 状态",
                "数据库统计",
                "系统统计",
                "现在几点",
                "几点了",
                "当前时间",
                "现在时间",
                "今天日期",
                "今天几号",
                "current time",
            ],
        )
        return explicit_mcp or explicit_capability

    @classmethod
    def is_system_stack_question(cls, message: str) -> bool:
        lowered = message.lower()
        subject = cls._contains_any(lowered, ["本系统", "本项目", "本博客", "博客系统", "这个项目", "技术栈"])
        stack = cls._contains_any(lowered, ["技术栈", "使用了什么技术", "用了哪些技术", "系统架构"])
        return subject and stack

    @classmethod
    def select_mcp_tool_name(cls, message: str) -> str:
        lowered = message.lower()
        if cls._contains_any(
            lowered,
            ["现在几点", "几点了", "当前时间", "现在时间", "今天日期", "今天几号", "current time", "what time"],
        ):
            return "current_time"
        if cls._contains_any(lowered, ["git", "仓库", "提交", "分支"]):
            return "git_repo_info"
        if cls._contains_any(lowered, ["网页", "联网", "网络搜索", "网上搜索", "互联网", "web"]):
            return "web_search"
        if cls._contains_any(lowered, ["数据库统计", "数据统计", "系统统计", "业务统计", "统计", "数量"]):
            return "safe_database_stats"
        return "local_file_search"

    def _run_writing_agent(self, message: str, history: list[dict[str, str]] | None = None) -> MultiAgentResponse:
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

        response = self.rag_agent.direct_chat(message, history=history or [])
        return self._from_agent_response(
            response,
            self._decision("writing_agent", "General LLM Agent", "general model knowledge without retrieval", 0.9),
            ["general_llm_agent -> no retrieval"],
        )

    def _run_internet_agent(
        self,
        message: str,
        trace: list[str],
        history: list[dict[str, str]] | None = None,
    ) -> MultiAgentResponse:
        from django.utils import timezone

        from apps.agent_api.models import MCPTool
        from agent.mcp_tools import LocalMCPToolRunner

        decision = self._decision("mcp_tool_agent", "Internet + LLM Agent", "internet explicitly enabled", 0.98)
        try:
            tool = MCPTool.objects.get(name="web_search", workspace_key=self.workspace_key)
        except MCPTool.DoesNotExist:
            return self._plain_response(
                answer="联网搜索工具未注册，已停止联网回答。",
                tool_call=ToolResult("mcp_registry_lookup", "web_search", "tool not registered"),
                trace=[*trace, "internet_search -> tool not registered"],
                route="internet",
                decision=decision,
            )
        if not tool.is_enabled:
            return self._plain_response(
                answer="联网搜索当前已关闭，请管理员先启用网页搜索工具。",
                tool_call=ToolResult("mcp_registry_lookup", "web_search", "tool disabled"),
                trace=[*trace, "internet_search -> tool disabled"],
                route="internet",
                decision=decision,
            )
        if tool.requires_approval:
            return self._plain_response(
                answer="联网搜索需要管理员审批，本次没有直接访问互联网。",
                tool_call=ToolResult("mcp_approval_required", message, "tool=web_search"),
                trace=[*trace, "internet_search -> approval required"],
                route="internet",
                decision=decision,
            )
        search_query = self.rag_agent.rewrite_web_search_query(message, history or [])
        execution = LocalMCPToolRunner(self.project_root).run("web_search", search_query)
        tool.last_used_at = timezone.now()
        tool.save(update_fields=["last_used_at", "updated_at"])
        if self._web_search_output_unusable(execution.output):
            return self._plain_response(
                answer=execution.output,
                tool_call=ToolResult("mcp:web_search", search_query, execution.output),
                trace=[*trace, f"internet_query_rewrite -> {search_query}", "internet_search -> unavailable"],
                route="internet",
                decision=decision,
            )
        response = self.rag_agent.answer_with_external_context(
            message,
            execution.output,
            ToolResult("mcp:web_search", search_query, execution.output),
            history=history or [],
        )
        response_with_query_trace = AgentResponse(
            answer=response.answer,
            tool_calls=response.tool_calls,
            sources=response.sources,
            trace=[f"internet_query_rewrite -> {search_query}", *response.trace],
            route=response.route,
            token_usage=response.token_usage,
        )
        return self._from_agent_response(response_with_query_trace, decision, trace)

    @staticmethod
    def _web_search_output_unusable(output: str) -> bool:
        return output.startswith("网页搜索失败：") or output.startswith("网页搜索没有返回可用结果。")

    @classmethod
    def _routing_message(cls, message: str, history: list[dict[str, str]]) -> str:
        follow_up_markers = ["那", "它", "这个", "继续", "详细", "呢", "上述", "上面", "刚才", "然后"]
        is_follow_up = len(message) <= 18 or cls._contains_any(message.lower(), follow_up_markers)
        if not is_follow_up or not history:
            return message
        previous_user_messages = [item.get("content", "") for item in history if item.get("role") == "user"]
        if not previous_user_messages:
            return message
        return f"上一问题：{previous_user_messages[-1]}\n当前追问：{message}"

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
            decision=self._decision("review_agent", "Review Agent", "quality review", 1.0),
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
            decision=self._decision("admin_approval_agent", "Admin Approval Agent", "manual approval", 1.0),
        )

    def _plain_response(
        self,
        answer: str,
        tool_call: ToolResult,
        trace: list[str],
        route: str,
        decision: SupervisorDecision,
    ) -> MultiAgentResponse:
        return MultiAgentResponse(
            answer=answer,
            tool_calls=[tool_call],
            sources=[],
            trace=trace,
            route=route,
            token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            supervisor=decision,
        )

    def _format_blog_sources(self, sources) -> str:
        if not sources:
            return "No public blog sources found."
        return "\n\n".join(
            f"[{index}] {source.title}\nkind={source.kind}\nscore={source.score:.3f}\n{source.content}"
            for index, source in enumerate(sources, start=1)
        )

    @staticmethod
    def _contains_any(lowered: str, keywords: list[str]) -> bool:
        return any(keyword.lower() in lowered for keyword in keywords)
