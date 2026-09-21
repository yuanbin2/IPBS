import hashlib


import os


import re


import time


from datetime import timedelta


from pathlib import Path


from uuid import uuid4


from django.conf import settings


from django.contrib.auth import authenticate, get_user_model, login


from django.core.files.storage import default_storage


from django.core.files.base import ContentFile


from django.db import transaction


from django.db.models import Q


from django.shortcuts import get_object_or_404


from django.utils import timezone
from celery.result import AsyncResult


from rest_framework import status


from rest_framework.parsers import FormParser, MultiPartParser


from rest_framework.response import Response


from rest_framework.views import APIView


from agent.multi_agent import MultiAgentSupervisor


from agent.security import (
    context_from_request,
    detect_sensitive_input,
    issue_jwt_pair,
    normalize_workspace_key,
    redact_sensitive_output,
    role_allowed,
    security_enforced,
)


from ..services.blog import (
    get_or_create_category,
    publish_article_to_knowledge_base,
    set_article_tags,
    unique_slug,
)


from ..services.blog_agent import PublicBlogAgent


from ..models import (
    AgentRun,
    AgentObservation,
    ApprovalRequest,
    ArticleCategory,
    ArticleTag,
    BlogAgentMessage,
    BlogAgentSecurityEvent,
    BlogAgentSession,
    BlogArticle,
    BlogComment,
    Conversation,
    Document,
    EvaluationCase,
    EvaluationRun,
    KnowledgeBase,
    MCPTool,
    Message,
    SecurityAuditEvent,
    UserProfile,
)


from ..services.rag import get_default_knowledge_base, search_knowledge_base
from ..tasks import ingest_document_task
from ..serializers import *








DEFAULT_MESSAGE_LIMIT = 30


MAX_MESSAGE_LIMIT = 50


BLOG_AGENT_RATE_LIMIT = 12


BLOG_AGENT_RATE_WINDOW_SECONDS = 60


def get_workspace_key(request) -> str:
    return context_from_request(request).workspace_key


def get_conversation_owner(request) -> str:
    """Return the stable identity used to isolate private chat history."""
    return context_from_request(request).actor or "anonymous"


def audit_security_event(request, event_type: str, detail: str = "", metadata: dict | None = None) -> None:
    context = context_from_request(request)
    SecurityAuditEvent.objects.create(
        event_type=event_type,
        actor=context.actor,
        role=context.role,
        workspace_key=context.workspace_key,
        path=request.path[:240],
        detail=detail,
        metadata=metadata or {},
    )


def require_roles(request, allowed_roles: list[str]) -> Response | None:
    context = context_from_request(request)
    if not security_enforced():
        return None
    if context.authenticated and role_allowed(context.role, allowed_roles):
        return None
    audit_security_event(
        request,
        SecurityAuditEvent.EventType.ACCESS_DENIED,
        f"required roles: {', '.join(allowed_roles)}",
    )
    return Response(
        {
            "detail": "permission denied",
            "required_roles": allowed_roles,
            "current_role": context.role,
        },
        status=status.HTTP_403_FORBIDDEN,
    )


def serialize_security_context(request) -> dict:
    context = context_from_request(request)
    return {
        "actor": context.actor,
        "role": context.role,
        "workspace_key": context.workspace_key,
        "authenticated": context.authenticated,
        "security_enforced": security_enforced(),
    }


def get_message_limit(request) -> int:
    try:
        limit = int(request.query_params.get("limit", DEFAULT_MESSAGE_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_MESSAGE_LIMIT
    return max(1, min(limit, MAX_MESSAGE_LIMIT))


def request_ip_hash(request) -> str:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded_for.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
    if not ip:
        return ""
    return hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode("utf-8")).hexdigest()






DEFAULT_MCP_TOOLS = [
    {
        "name": "local_file_search",
        "display_name": "本地文件搜索",
        "description": "在 README、docs 和 agent 目录中搜索公开项目资料。",
        "category": MCPTool.Category.FILESYSTEM,
        "permission_scope": "read:project_public_files",
        "is_enabled": True,
    },
    {
        "name": "git_repo_info",
        "display_name": "Git 仓库信息",
        "description": "读取当前分支、最近提交和工作区状态。",
        "category": MCPTool.Category.GIT,
        "permission_scope": "read:git_metadata",
        "is_enabled": True,
    },
    {
        "name": "web_search",
        "display_name": "网页搜索",
        "description": "外部网页搜索工具占位，默认关闭。",
        "category": MCPTool.Category.WEB,
        "permission_scope": "network:web_search",
        "is_enabled": False,
    },
    {
        "name": "safe_database_stats",
        "display_name": "安全数据库统计",
        "description": "只返回业务聚合指标，不暴露表结构和敏感字段。",
        "category": MCPTool.Category.DATABASE,
        "permission_scope": "read:aggregate_stats",
        "is_enabled": True,
    },
]


def ensure_default_mcp_tools() -> None:
    for tool in DEFAULT_MCP_TOOLS:
        MCPTool.objects.get_or_create(name=tool["name"], defaults=tool)








def env_file_is_git_tracked() -> bool:
    env_path = Path(settings.BASE_DIR).parent / ".env"
    git_index = Path(settings.BASE_DIR).parent / ".git" / "index"
    if not env_path.exists() or not git_index.exists():
        return False
    try:
        import subprocess

        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", ".env"],
            cwd=Path(settings.BASE_DIR).parent,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def selected_agent_from_response(response_data: dict) -> str:
    supervisor = response_data.get("supervisor") or {}
    return str(supervisor.get("selected_agent") or "")


def calculate_tool_success_rate(tool_calls: list[dict]) -> float:
    if not tool_calls:
        return 1.0
    successful = 0
    for call in tool_calls:
        output = str(call.get("output", "")).lower()
        if output and not any(marker in output for marker in ["error", "failed", "异常", "失败"]):
            successful += 1
    return round(successful / len(tool_calls), 2)








def evaluate_answer(case: EvaluationCase, response_data: dict, observation: AgentObservation) -> dict:
    answer = str(response_data.get("answer", ""))
    selected_agent = selected_agent_from_response(response_data)
    keywords = [str(item).lower() for item in case.reference_keywords]
    answer_lower = answer.lower()
    keyword_hits = sum(1 for keyword in keywords if keyword and keyword in answer_lower)
    keyword_score = keyword_hits / len(keywords) if keywords else 1.0
    route_score = 1.0 if not case.expected_agent or selected_agent == case.expected_agent else 0.0
    citation_score = 1.0 if response_data.get("sources") else (0.7 if case.category == EvaluationCase.Category.JAILBREAK else 0.0)
    faithful_markers = ["不能", "无法", "审批", "知识库", "来源", "Agent", "RAG", "博客"]
    faithfulness = 1.0 if any(marker in answer for marker in faithful_markers) else 0.5
    correctness = round((keyword_score * 0.6) + (route_score * 0.4), 2)
    return {
        "answer_correctness": correctness,
        "faithfulness": faithfulness,
        "citation_accuracy": citation_score,
        "latency_ms": observation.latency_ms,
        "tool_success_rate": observation.tool_success_rate,
        "selected_agent": selected_agent,
        "expected_agent": case.expected_agent,
    }


def create_agent_observation(
    *,
    conversation: Conversation | None,
    agent_run: AgentRun | None,
    input_message: str,
    workspace_key: str = "default",
    response_data: dict | None = None,
    latency_ms: int = 0,
    failure_reason: str = "",
) -> AgentObservation:
    response_data = response_data or {}
    tool_calls = response_data.get("tool_calls", [])
    return AgentObservation.objects.create(
        conversation=conversation,
        agent_run=agent_run,
        input_message=input_message,
        workspace_key=workspace_key,
        answer=str(response_data.get("answer", "")),
        route=str(response_data.get("route", "")),
        selected_agent=selected_agent_from_response(response_data),
        trace=response_data.get("trace", []),
        tool_calls=tool_calls,
        sources=response_data.get("sources", []),
        token_usage=response_data.get("token_usage", {}),
        latency_ms=latency_ms,
        tool_success_rate=calculate_tool_success_rate(tool_calls),
        status=AgentObservation.Status.FAILED if failure_reason else AgentObservation.Status.SUCCESS,
        failure_reason=failure_reason,
        langsmith_project=os.environ.get("LANGSMITH_PROJECT", ""),
        langsmith_run_id=str(response_data.get("langsmith_run_id", "")),
    )


def observability_summary(workspace_key: str | None = None) -> dict:
    observations = AgentObservation.objects.all()
    if workspace_key:
        observations = observations.filter(workspace_key=workspace_key)
    total = observations.count()
    if total == 0:
        return {
            "total_runs": 0,
            "success_rate": 1.0,
            "average_latency_ms": 0,
            "average_tool_success_rate": 1.0,
            "failed_runs": 0,
            "langsmith_enabled": bool(os.environ.get("LANGSMITH_API_KEY")),
            "langsmith_project": os.environ.get("LANGSMITH_PROJECT", ""),
        }

    successful = observations.filter(status=AgentObservation.Status.SUCCESS).count()
    latency_sum = sum(item.latency_ms for item in observations[:200])
    tool_rate_sum = sum(item.tool_success_rate for item in observations[:200])
    sample_count = min(total, 200)
    return {
        "total_runs": total,
        "success_rate": round(successful / total, 2),
        "average_latency_ms": round(latency_sum / sample_count),
        "average_tool_success_rate": round(tool_rate_sum / sample_count, 2),
        "failed_runs": total - successful,
        "langsmith_enabled": bool(os.environ.get("LANGSMITH_API_KEY")),
        "langsmith_project": os.environ.get("LANGSMITH_PROJECT", ""),
    }


def approval_required_response(approval: ApprovalRequest) -> Response:
    return Response(
        {
            "approval_required": True,
            "detail": "该操作已进入人工审批队列，审批通过后才会执行。",
            "approval": serialize_approval_request(approval),
        },
        status=status.HTTP_202_ACCEPTED,
    )




def extract_blog_delete_target(message: str) -> str:
    if not any(keyword in message for keyword in ["删除文章", "删除博客", "删掉文章", "删掉博客"]):
        return ""
    quoted = re.search(r"[《「\"]([^》」\"]+)[》」\"]", message)
    if quoted:
        return quoted.group(1).strip()
    cleaned = re.sub(r"(请|帮我|删除|删掉|文章|博客|这篇|一下|吧|。|，|,)", " ", message)
    return re.sub(r"\s+", " ", cleaned).strip()


def maybe_create_blog_delete_approval(message: str, request) -> ApprovalRequest | None:
    target = extract_blog_delete_target(message)
    if not target:
        return None
    article = (
        BlogArticle.objects.filter(workspace_key=get_workspace_key(request), title__icontains=target)
        .order_by("-updated_at")
        .first()
    )
    if not article:
        article = (
            BlogArticle.objects.filter(workspace_key=get_workspace_key(request), slug__icontains=target)
            .order_by("-updated_at")
            .first()
        )
    if not article:
        return None
    return ApprovalRequest.objects.create(
        action=ApprovalRequest.Action.DELETE_BLOG_ARTICLE,
        workspace_key=get_workspace_key(request),
        title=f"删除博客：{article.title}",
        description="对话触发的删除博客请求，需要管理员审批后才会删除文章和对应知识库文档。",
        payload={"article_slug": article.slug, "article_id": article.id, "title": article.title},
        requester=str(request.data.get("requester", "chat-agent")).strip() if hasattr(request, "data") else "chat-agent",
    )


def maybe_create_mcp_approval(message: str, request) -> ApprovalRequest | None:
    if not MultiAgentSupervisor.is_mcp_request(message):
        return None
    tool_name = MultiAgentSupervisor.select_mcp_tool_name(message)
    tool = MCPTool.objects.filter(
        name=tool_name,
        workspace_key=get_workspace_key(request),
        is_enabled=True,
        requires_approval=True,
    ).first()
    if not tool:
        return None
    return ApprovalRequest.objects.create(
        action=ApprovalRequest.Action.EXECUTE_MCP_TOOL,
        workspace_key=get_workspace_key(request),
        title=f"执行 MCP 工具：{tool.display_name}",
        description=f"聊天请求调用工具；权限范围：{tool.permission_scope}",
        payload={"tool_id": tool.id, "tool_name": tool.name, "query": message},
        requester=serialize_security_context(request)["actor"],
    )


def execute_approval_request(approval: ApprovalRequest) -> str:
    payload = approval.payload or {}

    if approval.action == ApprovalRequest.Action.DELETE_DOCUMENT:
        document = get_object_or_404(Document, pk=payload.get("document_id"), workspace_key=approval.workspace_key)
        title = document.title
        if document.source_file:
            document.source_file.delete(save=False)
        document.delete()
        return f"文档已删除：{title}"

    if approval.action == ApprovalRequest.Action.DELETE_KNOWLEDGE_BASE:
        knowledge_base = get_object_or_404(KnowledgeBase, pk=payload.get("knowledge_base_id"), workspace_key=approval.workspace_key)
        name = knowledge_base.name
        knowledge_base.delete()
        return f"知识库已删除：{name}"

    if approval.action == ApprovalRequest.Action.DELETE_BLOG_ARTICLE:
        article = get_object_or_404(BlogArticle, slug=payload.get("article_slug"), workspace_key=approval.workspace_key)
        title = article.title
        knowledge_document = article.knowledge_document
        article.delete()
        if knowledge_document:
            if knowledge_document.source_file:
                knowledge_document.source_file.delete(save=False)
            knowledge_document.delete()
        return f"博客文章已删除：{title}"

    if approval.action == ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE:
        article = get_object_or_404(BlogArticle, slug=payload.get("article_slug"), workspace_key=approval.workspace_key)
        publish_article_to_knowledge_base(article)
        return f"博客文章已发布并同步知识库：{article.title}"

    if approval.action == ApprovalRequest.Action.EXECUTE_MCP_TOOL and payload.get("tool_name"):
        from agent.mcp_tools import LocalMCPToolRunner

        tool = get_object_or_404(MCPTool, pk=payload.get("tool_id"), workspace_key=approval.workspace_key)
        if not tool.is_enabled:
            raise ValueError(f"MCP 工具已禁用：{tool.display_name}")
        execution = LocalMCPToolRunner(Path(settings.BASE_DIR).parent).run(tool.name, str(payload.get("query", "")))
        tool.last_used_at = timezone.now()
        tool.save(update_fields=["last_used_at", "updated_at"])
        return f"MCP 工具已执行：{tool.display_name}\n\n{execution.output}"

    return "该审批类型当前只记录审批结果，未绑定自动执行器。"
