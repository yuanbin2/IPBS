"""专用 Agent 的执行实现：博客、SQL 统计、MCP 工具、写作、联网、审查与审批拦截。

每个函数显式接收所需上下文（project_root / workspace_key / rag_agent），
不依赖 Supervisor 实例状态；MCP 相关路径都先查数据库中的工具白名单
（注册、启用、审批），实现存在不代表可执行。
"""

from __future__ import annotations

from .agent_types import (
    AgentResponse,
    MultiAgentResponse,
    SourceCitation,
    SupervisorDecision,
    TokenUsage,
)
from .security import redact_sensitive_output
from .supervisor_routing import contains_any, decision
from .tools import ToolResult

_EMPTY_USAGE: TokenUsage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

# runner 对失败只生成这些固定前缀的消息；正文内容不参与判定，
# 否则检索/执行输出里恰好出现的「失败/error」等词会造成误判。
MCP_FAILURE_PREFIXES = ("网页搜索失败：", "网页搜索没有返回可用结果。", "工具执行失败")


def mcp_execution_ok(output: str) -> bool:
    return not output.startswith(MCP_FAILURE_PREFIXES)


def plain_response(
    answer: str,
    tool_call: ToolResult,
    trace: list[str],
    route: str,
    supervisor_decision: SupervisorDecision,
) -> MultiAgentResponse:
    return MultiAgentResponse(
        answer=answer,
        tool_calls=[tool_call],
        sources=[],
        trace=trace,
        route=route,
        token_usage=dict(_EMPTY_USAGE),
        supervisor=supervisor_decision,
    )


def format_blog_sources(sources) -> str:
    if not sources:
        return "No public blog sources found."
    return "\n\n".join(
        f"[{index}] {source.title}\nkind={source.kind}\nscore={source.score:.3f}\n{source.content}"
        for index, source in enumerate(sources, start=1)
    )


def from_agent_response(
    response: AgentResponse,
    supervisor_decision: SupervisorDecision,
    trace: list[str],
    redact,
) -> MultiAgentResponse:
    """把 RAG Agent 响应包装成 Supervisor 响应，并做输出脱敏。"""
    answer, redacted = redact(response.answer)
    extra_trace = ["security_filter -> output redacted"] if redacted else []
    return MultiAgentResponse(
        answer=answer,
        tool_calls=response.tool_calls,
        sources=response.sources,
        trace=[*trace, *response.trace, *extra_trace],
        route=response.route,
        token_usage=response.token_usage,
        supervisor=supervisor_decision,
    )


def run_blog_agent(project_root, message: str, history: list[dict[str, str]] | None = None) -> MultiAgentResponse:
    from apps.agent_api.services.blog_agent import PublicBlogAgent

    blog_agent = PublicBlogAgent(project_root)
    answer = blog_agent.answer(message, history=history or [])
    tool_calls = [
        ToolResult(
            name="blog_agent_search",
            input=message,
            output=format_blog_sources(answer.sources),
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
        supervisor=decision("blog_agent", "Blog Agent", "blog route", 1.0),
    )


def run_sql_analysis_agent(message: str) -> MultiAgentResponse:
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
    return plain_response(
        answer=answer,
        tool_call=ToolResult("safe_sql_analytics", message, output),
        trace=["sql_analysis_agent -> safe aggregate query completed"],
        route="sql_analysis_agent",
        supervisor_decision=decision("sql_analysis_agent", "SQL Analysis Agent", "safe aggregate query", 1.0),
    )


def run_mcp_tool_agent(project_root, workspace_key: str, message: str) -> MultiAgentResponse:
    from django.utils import timezone

    from agent.mcp_tools import LocalMCPToolRunner
    from apps.agent_api.models import MCPTool

    from .supervisor_routing import select_mcp_tool_name

    selected_tool = select_mcp_tool_name(message)

    # 数据库中的 MCPTool 是工具白名单和权限来源。即使代码中存在
    # runner，实现未注册、停用或高风险的工具也不能被直接执行。
    try:
        registry_item = MCPTool.objects.get(name=selected_tool, workspace_key=workspace_key)
    except MCPTool.DoesNotExist:
        return plain_response(
            answer=f"MCP Tool Agent 没有找到注册工具：{selected_tool}",
            tool_call=ToolResult("mcp_registry_lookup", selected_tool, "tool not registered", ok=False),
            trace=["mcp_tool_agent -> registry lookup failed"],
            route="mcp_tool_agent",
            supervisor_decision=decision("mcp_tool_agent", "MCP Tool Agent", "registry lookup", 1.0),
        )

    if not registry_item.is_enabled:
        return plain_response(
            answer=f"MCP 工具「{registry_item.display_name}」当前已禁用，需要管理员在工具注册表中启用后才能调用。",
            tool_call=ToolResult("mcp_registry_lookup", selected_tool, "tool disabled", ok=False),
            trace=["mcp_tool_agent -> tool disabled"],
            route="mcp_tool_agent",
            supervisor_decision=decision("mcp_tool_agent", "MCP Tool Agent", "tool disabled", 1.0),
        )

    if registry_item.requires_approval:
        return plain_response(
            answer=f"MCP 工具「{registry_item.display_name}」需要管理员审批，请通过聊天 API 创建审批单后执行。",
            tool_call=ToolResult("mcp_approval_required", message, f"tool={selected_tool}"),
            trace=["mcp_tool_agent -> approval required"],
            route="mcp_tool_agent",
            supervisor_decision=decision("mcp_tool_agent", "MCP Tool Agent", "tool requires approval", 1.0),
        )

    execution = LocalMCPToolRunner(project_root).run(selected_tool, message)
    registry_item.last_used_at = timezone.now()
    registry_item.save(update_fields=["last_used_at", "updated_at"])
    answer = (
        f"MCP Tool Agent 调用了「{registry_item.display_name}」。\n\n"
        f"权限范围：{registry_item.permission_scope}\n\n"
        f"{execution.output}"
    )
    return plain_response(
        answer=answer,
        tool_call=ToolResult(f"mcp:{selected_tool}", message, execution.output, ok=mcp_execution_ok(execution.output)),
        trace=[f"mcp_tool_agent -> {selected_tool}"],
        route="mcp_tool_agent",
        supervisor_decision=decision("mcp_tool_agent", "MCP Tool Agent", "tool execution", 1.0),
    )


def run_writing_agent(rag_agent, message: str, history: list[dict[str, str]] | None = None) -> MultiAgentResponse:
    if contains_any(message.lower(), ["笑话", "joke", "ц", "瑧璇"]):
        return MultiAgentResponse(
            answer="Writing Agent：当然可以。为什么程序员喜欢深色模式？因为光会吸引 bug。",
            tool_calls=[],
            sources=[],
            trace=["writing_agent -> casual direct answer"],
            route="direct",
            token_usage=dict(_EMPTY_USAGE),
            supervisor=decision("writing_agent", "Writing Agent", "casual direct answer", 1.0),
        )

    response = rag_agent.direct_chat(message, history=history or [])
    return from_agent_response(
        response,
        decision("writing_agent", "General LLM Agent", "general model knowledge without retrieval", 0.9),
        ["general_llm_agent -> no retrieval"],
        redact_sensitive_output,
    )


def run_internet_agent(
    rag_agent,
    project_root,
    workspace_key: str,
    message: str,
    trace: list[str],
    history: list[dict[str, str]] | None = None,
) -> MultiAgentResponse:
    from django.utils import timezone

    from agent.mcp_tools import LocalMCPToolRunner
    from apps.agent_api.models import MCPTool

    from .supervisor_routing import web_search_output_unusable

    internet_decision = decision("mcp_tool_agent", "Internet + LLM Agent", "internet explicitly enabled", 0.98)
    try:
        tool = MCPTool.objects.get(name="web_search", workspace_key=workspace_key)
    except MCPTool.DoesNotExist:
        return plain_response(
            answer="联网搜索工具未注册，已停止联网回答。",
            tool_call=ToolResult("mcp_registry_lookup", "web_search", "tool not registered", ok=False),
            trace=[*trace, "internet_search -> tool not registered"],
            route="internet",
            supervisor_decision=internet_decision,
        )
    if not tool.is_enabled:
        return plain_response(
            answer="联网搜索当前已关闭，请管理员先启用网页搜索工具。",
            tool_call=ToolResult("mcp_registry_lookup", "web_search", "tool disabled", ok=False),
            trace=[*trace, "internet_search -> tool disabled"],
            route="internet",
            supervisor_decision=internet_decision,
        )
    if tool.requires_approval:
        return plain_response(
            answer="联网搜索需要管理员审批，本次没有直接访问互联网。",
            tool_call=ToolResult("mcp_approval_required", message, "tool=web_search"),
            trace=[*trace, "internet_search -> approval required"],
            route="internet",
            supervisor_decision=internet_decision,
        )
    search_query = rag_agent.rewrite_web_search_query(message, history or [])
    execution = LocalMCPToolRunner(project_root).run("web_search", search_query)
    tool.last_used_at = timezone.now()
    tool.save(update_fields=["last_used_at", "updated_at"])
    if web_search_output_unusable(execution.output):
        return plain_response(
            answer=execution.output,
            tool_call=ToolResult(
                "mcp:web_search", search_query, execution.output, ok=mcp_execution_ok(execution.output)
            ),
            trace=[*trace, f"internet_query_rewrite -> {search_query}", "internet_search -> unavailable"],
            route="internet",
            supervisor_decision=internet_decision,
        )
    response = rag_agent.answer_with_external_context(
        message,
        execution.output,
        ToolResult("mcp:web_search", search_query, execution.output, ok=mcp_execution_ok(execution.output)),
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
    return from_agent_response(response_with_query_trace, internet_decision, trace, redact_sensitive_output)


def run_review_agent(message: str) -> MultiAgentResponse:
    answer = (
        "Review Agent 已接手。当前审查结论：\n\n"
        "- 优先检查回答是否引用了知识库或博客来源。\n"
        "- 对没有来源支撑的结论，应标记为推断或建议。\n"
        "- 对涉及后台结构、API Key、数据库字段和管理信息的问题，应拒绝或转交 Admin Approval Agent。\n"
        "- 对写作类输出，重点检查是否跑题、是否有明显事实风险。\n\n"
        f"待审查内容：{message}"
    )
    return plain_response(
        answer=answer,
        tool_call=ToolResult("answer_review", message, "quality and safety review checklist generated"),
        trace=["review_agent -> quality checklist generated"],
        route="review_agent",
        supervisor_decision=decision("review_agent", "Review Agent", "quality review", 1.0),
    )


def run_admin_approval_agent(message: str) -> MultiAgentResponse:
    answer = (
        "Admin Approval Agent 已拦截该请求。\n\n"
        "这个 Agent 只给出审批建议，不直接执行高风险动作。涉及删除、权限、后台配置、API Key、数据库结构、"
        "用户隐私或发布审核的问题，需要明确管理员确认，并保留操作记录。\n\n"
        f"当前请求：{message}\n\n"
        "建议状态：需要人工确认。"
    )
    return plain_response(
        answer=answer,
        tool_call=ToolResult("admin_approval", message, "manual approval required"),
        trace=["admin_approval_agent -> manual approval required"],
        route="admin_approval_agent",
        supervisor_decision=decision("admin_approval_agent", "Admin Approval Agent", "manual approval", 1.0),
    )
