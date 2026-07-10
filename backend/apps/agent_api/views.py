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
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.multi_agent import MultiAgentSupervisor
from agent.security import (
    context_from_request,
    detect_sensitive_input,
    issue_signed_token,
    normalize_workspace_key,
    redact_sensitive_output,
    role_allowed,
    security_enforced,
)

from .blog import (
    get_or_create_category,
    publish_article_to_knowledge_base,
    serialize_article,
    serialize_category,
    serialize_tag,
    set_article_tags,
    unique_slug,
)
from .blog_agent import PublicBlogAgent
from .models import (
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
from .rag import get_default_knowledge_base, ingest_document, search_knowledge_base


def serialize_message(message: Message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "tool_calls": message.tool_calls,
        "sources": message.sources,
        "trace": message.trace,
        "token_usage": message.token_usage,
        "created_at": message.created_at.isoformat(),
    }


def serialize_knowledge_base(knowledge_base: KnowledgeBase) -> dict:
    return {
        "id": knowledge_base.id,
        "name": knowledge_base.name,
        "description": knowledge_base.description,
        "document_count": knowledge_base.documents.count(),
        "chunk_count": knowledge_base.chunks.count(),
        "created_at": knowledge_base.created_at.isoformat(),
        "updated_at": knowledge_base.updated_at.isoformat(),
    }


def serialize_document(document: Document) -> dict:
    return {
        "id": document.id,
        "knowledge_base_id": document.knowledge_base_id,
        "title": document.title,
        "content_type": document.content_type,
        "status": document.status,
        "error_message": document.error_message,
        "chunk_count": document.chunk_count,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


DEFAULT_MESSAGE_LIMIT = 30
MAX_MESSAGE_LIMIT = 50
BLOG_AGENT_RATE_LIMIT = 12
BLOG_AGENT_RATE_WINDOW_SECONDS = 60


def get_workspace_key(request) -> str:
    return context_from_request(request).workspace_key


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


def serialize_blog_agent_message(message: BlogAgentMessage) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "sources": message.sources,
        "trace": message.trace,
        "token_usage": message.token_usage,
        "created_at": message.created_at.isoformat(),
    }


def serialize_approval_request(approval: ApprovalRequest) -> dict:
    return {
        "id": approval.id,
        "action": approval.action,
        "action_label": approval.get_action_display(),
        "title": approval.title,
        "description": approval.description,
        "payload": approval.payload,
        "status": approval.status,
        "requester": approval.requester,
        "reviewer": approval.reviewer,
        "review_note": approval.review_note,
        "result": approval.result,
        "created_at": approval.created_at.isoformat(),
        "reviewed_at": approval.reviewed_at.isoformat() if approval.reviewed_at else None,
        "executed_at": approval.executed_at.isoformat() if approval.executed_at else None,
    }


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


def serialize_mcp_tool(tool: MCPTool) -> dict:
    return {
        "id": tool.id,
        "name": tool.name,
        "display_name": tool.display_name,
        "description": tool.description,
        "category": tool.category,
        "permission_scope": tool.permission_scope,
        "is_enabled": tool.is_enabled,
        "requires_approval": tool.requires_approval,
        "config": tool.config,
        "last_used_at": tool.last_used_at.isoformat() if tool.last_used_at else None,
        "created_at": tool.created_at.isoformat(),
        "updated_at": tool.updated_at.isoformat(),
    }


def serialize_user_profile(profile: UserProfile) -> dict:
    return {
        "user_id": profile.user_id,
        "username": profile.user.username,
        "role": profile.role,
        "workspace_key": profile.workspace_key,
    }


def serialize_security_audit_event(event: SecurityAuditEvent) -> dict:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "actor": event.actor,
        "role": event.role,
        "workspace_key": event.workspace_key,
        "path": event.path,
        "detail": event.detail,
        "metadata": event.metadata,
        "created_at": event.created_at.isoformat(),
    }


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


def serialize_agent_observation(observation: AgentObservation) -> dict:
    return {
        "id": observation.id,
        "conversation_id": observation.conversation_id,
        "agent_run_id": observation.agent_run_id,
        "input_message": observation.input_message,
        "answer": observation.answer,
        "route": observation.route,
        "selected_agent": observation.selected_agent,
        "trace": observation.trace,
        "tool_calls": observation.tool_calls,
        "sources": observation.sources,
        "token_usage": observation.token_usage,
        "latency_ms": observation.latency_ms,
        "tool_success_rate": observation.tool_success_rate,
        "status": observation.status,
        "failure_reason": observation.failure_reason,
        "langsmith_project": observation.langsmith_project,
        "langsmith_run_id": observation.langsmith_run_id,
        "created_at": observation.created_at.isoformat(),
    }


def serialize_evaluation_case(case: EvaluationCase) -> dict:
    latest_run = case.runs.first()
    return {
        "id": case.id,
        "question": case.question,
        "expected_answer": case.expected_answer,
        "category": case.category,
        "expected_route": case.expected_route,
        "expected_agent": case.expected_agent,
        "reference_keywords": case.reference_keywords,
        "is_active": case.is_active,
        "created_at": case.created_at.isoformat(),
        "latest_run": serialize_evaluation_run(latest_run) if latest_run else None,
    }


def serialize_evaluation_run(run: EvaluationRun) -> dict:
    return {
        "id": run.id,
        "case_id": run.case_id,
        "observation_id": run.observation_id,
        "answer": run.answer,
        "metrics": run.metrics,
        "passed": run.passed,
        "created_at": run.created_at.isoformat(),
    }


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


def serialize_conversation(
    conversation: Conversation,
    include_messages: bool = False,
    messages: list[Message] | None = None,
    has_more_before: bool = False,
    has_more_after: bool = False,
    matched_message_id: int | None = None,
) -> dict:
    data = {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }
    if matched_message_id:
        data["matched_message_id"] = matched_message_id
    if include_messages:
        selected_messages = messages if messages is not None else list(conversation.messages.all())
        data["messages"] = [serialize_message(message) for message in selected_messages]
        data["has_more_before"] = has_more_before
        data["has_more_after"] = has_more_after
    return data


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


class AuthLoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        username = str(request.data.get("username", "")).strip()
        password = str(request.data.get("password", ""))
        if not username or not password:
            return Response({"detail": "username and password are required"}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response({"detail": "invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

        login(request, user)
        token = issue_signed_token(user)
        profile = user.agent_profile
        audit_security_event(
            request,
            SecurityAuditEvent.EventType.LOGIN,
            "login succeeded",
            {"username": username, "role": profile.role},
        )
        return Response(
            {
                "token": token,
                "user": serialize_user_profile(profile),
                "session": serialize_security_context(request),
            }
        )


class AuthRegisterView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        username = str(request.data.get("username", "")).strip()
        password = str(request.data.get("password", ""))
        role = str(request.data.get("role", UserProfile.Role.ADMIN)).strip().lower()
        workspace_key = normalize_workspace_key(request.data.get("workspace_key", "default"))
        if not username or not password:
            return Response({"detail": "username and password are required"}, status=status.HTTP_400_BAD_REQUEST)
        if len(password) < 8:
            return Response({"detail": "password must be at least 8 characters"}, status=status.HTTP_400_BAD_REQUEST)
        if role not in {UserProfile.Role.ADMIN, UserProfile.Role.OPERATOR, UserProfile.Role.VISITOR}:
            role = UserProfile.Role.ADMIN

        User = get_user_model()
        if User.objects.filter(username=username).exists():
            return Response({"detail": "username already exists"}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.create_user(username=username, password=password, is_staff=role == UserProfile.Role.ADMIN)
        profile, _ = UserProfile.objects.update_or_create(
            user=user,
            defaults={"role": role, "workspace_key": workspace_key},
        )
        token = issue_signed_token(user)
        audit_security_event(
            request,
            SecurityAuditEvent.EventType.LOGIN,
            "registration succeeded",
            {"username": username, "role": role, "workspace_key": workspace_key},
        )
        return Response(
            {
                "token": token,
                "user": serialize_user_profile(profile),
                "session": {
                    "actor": user.username,
                    "role": profile.role,
                    "workspace_key": profile.workspace_key,
                    "authenticated": True,
                    "security_enforced": security_enforced(),
                },
            },
            status=status.HTTP_201_CREATED,
        )


class AuthMeView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response(serialize_security_context(request))


class SecurityStatusView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        env_exists = (Path(settings.BASE_DIR).parent / ".env").exists()
        return Response(
            {
                "context": serialize_security_context(request),
                "checks": {
                    "security_enforced": security_enforced(),
                    "env_file_exists": env_exists,
                    "env_file_git_tracked": env_file_is_git_tracked(),
                    "debug": settings.DEBUG,
                    "allowed_hosts": settings.ALLOWED_HOSTS,
                    "langsmith_configured": bool(os.environ.get("LANGSMITH_API_KEY")),
                    "secret_values_returned": False,
                },
                "guidance": [
                    ".env 只保存在部署环境，不提交到 Git。",
                    "生产环境开启 AGENT_SECURITY_ENFORCED 并使用管理员账号登录。",
                    "工具默认白名单管理，高风险动作进入人工审批。",
                    "SQL 类能力只允许只读聚合查询。",
                ],
            }
        )


class SecurityAuditListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        workspace_key = get_workspace_key(request)
        events = SecurityAuditEvent.objects.filter(workspace_key=workspace_key)[:100]
        return Response([serialize_security_audit_event(event) for event in events])


class ConversationListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        query = str(request.query_params.get("q", "")).strip()
        conversations = Conversation.objects.filter(workspace_key=get_workspace_key(request))
        if query:
            conversations = conversations.filter(
                Q(title__icontains=query) | Q(messages__content__icontains=query)
            ).distinct()

        results = []
        for conversation in conversations[:30]:
            matched_message_id = None
            if query:
                match = conversation.messages.filter(content__icontains=query).first()
                matched_message_id = match.id if match else None
            results.append(
                serialize_conversation(
                    conversation,
                    matched_message_id=matched_message_id,
                )
            )
        return Response(results)


class ConversationDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, pk: int):
        conversation = get_object_or_404(Conversation, pk=pk, workspace_key=get_workspace_key(request))
        limit = get_message_limit(request)
        before = request.query_params.get("before")
        anchor = request.query_params.get("anchor")

        messages_queryset = conversation.messages.all()
        has_more_after = False

        if anchor:
            anchor_message = get_object_or_404(messages_queryset, pk=anchor)
            before_count = max(1, limit // 2)
            after_count = max(0, limit - before_count)
            before_messages = list(
                messages_queryset.filter(id__lte=anchor_message.id).order_by("-id")[:before_count]
            )
            after_messages = list(
                messages_queryset.filter(id__gt=anchor_message.id).order_by("id")[:after_count]
            )
            messages = [*reversed(before_messages), *after_messages]
            has_more_after = messages_queryset.filter(id__gt=messages[-1].id).exists() if messages else False
        elif before:
            messages = list(messages_queryset.filter(id__lt=before).order_by("-id")[:limit])
            messages = list(reversed(messages))
        else:
            messages = list(messages_queryset.order_by("-id")[:limit])
            messages = list(reversed(messages))

        has_more_before = messages_queryset.filter(id__lt=messages[0].id).exists() if messages else False
        return Response(
            serialize_conversation(
                conversation,
                include_messages=True,
                messages=messages,
                has_more_before=has_more_before,
                has_more_after=has_more_after,
            )
        )


class AgentChatView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        message = str(request.data.get("message", "")).strip()
        if not message:
            return Response(
                {"detail": "message is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        workspace_key = get_workspace_key(request)
        sensitive_marker = detect_sensitive_input(message)
        if sensitive_marker:
            audit_security_event(
                request,
                SecurityAuditEvent.EventType.SENSITIVE_INPUT,
                "chat input matched security filter",
                {"pattern": sensitive_marker},
            )

        conversation = self._get_or_create_conversation(request.data.get("conversation_id"), message, workspace_key)
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.USER,
            content=message,
        )

        approval = maybe_create_blog_delete_approval(message, request)
        if approval:
            response_data = {
                "answer": f"已为文章删除创建审批单 #{approval.id}。管理员批准后才会删除：{approval.payload.get('title')}",
                "tool_calls": [
                    {
                        "name": "admin_approval",
                        "input": message,
                        "output": f"approval_id={approval.id}; action={approval.action}",
                    }
                ],
                "sources": [],
                "trace": [
                    "supervisor -> received request",
                    "supervisor -> admin_approval_agent (blog deletion requires approval)",
                    "admin_approval_agent -> approval request created",
                ],
                "route": "admin_approval_agent",
                "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "supervisor": {
                    "selected_agent": "admin_approval_agent",
                    "display_name": "Admin Approval Agent",
                    "reason": "blog deletion requires human approval",
                    "confidence": 0.98,
                    "handoff": "handoff -> Admin Approval Agent",
                },
            }
            Message.objects.create(
                conversation=conversation,
                role=Message.Role.AGENT,
                content=response_data["answer"],
                tool_calls=response_data["tool_calls"],
                sources=response_data["sources"],
                trace=response_data["trace"],
                token_usage=response_data["token_usage"],
            )
            agent_run = AgentRun.objects.create(
                conversation=conversation,
                workspace_key=workspace_key,
                input_message=message,
                route=response_data["route"],
                tool_calls=response_data["tool_calls"],
                sources=response_data["sources"],
                trace=response_data["trace"],
                token_usage=response_data["token_usage"],
            )
            observation = create_agent_observation(
                conversation=conversation,
                agent_run=agent_run,
                input_message=message,
                workspace_key=workspace_key,
                response_data=response_data,
            )
            conversation.save(update_fields=["updated_at"])
            return Response(
                {
                    **response_data,
                    "approval_required": True,
                    "approval": serialize_approval_request(approval),
                    "conversation": serialize_conversation(conversation),
                    "observation": serialize_agent_observation(observation),
                },
                status=status.HTTP_202_ACCEPTED,
            )

        project_root = Path(settings.BASE_DIR).parent
        started_at = time.perf_counter()
        try:
            agent = MultiAgentSupervisor(project_root)
            response = agent.chat(message)
            response_data = response.to_dict()
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started_at) * 1000)
            create_agent_observation(
                conversation=conversation,
                agent_run=None,
                input_message=message,
                workspace_key=workspace_key,
                latency_ms=latency_ms,
                failure_reason=str(exc),
            )
            raise

        Message.objects.create(
            conversation=conversation,
            role=Message.Role.AGENT,
            content=response.answer,
            tool_calls=response_data["tool_calls"],
            sources=response_data["sources"],
            trace=response.trace,
            token_usage=response.token_usage,
        )
        agent_run = AgentRun.objects.create(
            conversation=conversation,
            workspace_key=workspace_key,
            input_message=message,
            route=response.route,
            tool_calls=response_data["tool_calls"],
            sources=response_data["sources"],
            trace=response.trace,
            token_usage=response.token_usage,
        )
        observation = create_agent_observation(
            conversation=conversation,
            agent_run=agent_run,
            input_message=message,
            workspace_key=workspace_key,
            response_data=response_data,
            latency_ms=round((time.perf_counter() - started_at) * 1000),
        )
        if any(item == "security_filter -> output redacted" for item in response.trace):
            audit_security_event(request, SecurityAuditEvent.EventType.OUTPUT_REDACTED, "agent output redacted")

        conversation.save(update_fields=["updated_at"])
        return Response(
            {
                **response_data,
                "conversation": serialize_conversation(conversation),
                "observation": serialize_agent_observation(observation),
            }
        )

    def _get_or_create_conversation(self, conversation_id, message: str, workspace_key: str) -> Conversation:
        if conversation_id:
            return get_object_or_404(Conversation, pk=conversation_id, workspace_key=workspace_key)

        title = message[:40]
        if len(message) > 40:
            title = f"{title}..."
        return Conversation.objects.create(title=title, workspace_key=workspace_key)


class ObservabilityDashboardView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        limit = min(int(request.query_params.get("limit", 30)), 100)
        observations = AgentObservation.objects.select_related("conversation", "agent_run").filter(
            workspace_key=get_workspace_key(request)
        )[:limit]
        return Response(
            {
                "summary": observability_summary(get_workspace_key(request)),
                "observations": [serialize_agent_observation(observation) for observation in observations],
            }
        )


class EvaluationCaseListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        category = request.query_params.get("category")
        cases = EvaluationCase.objects.prefetch_related("runs").filter(workspace_key=get_workspace_key(request))
        if category and category != "all":
            cases = cases.filter(category=category)
        return Response([serialize_evaluation_case(case) for case in cases])


class EvaluationRunView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        case_id = request.data.get("case_id")
        limit = request.data.get("limit", 5)
        try:
            limit = max(1, min(int(limit), 30))
        except (TypeError, ValueError):
            limit = 5

        workspace_key = get_workspace_key(request)
        if case_id:
            cases = [get_object_or_404(EvaluationCase, pk=case_id, workspace_key=workspace_key)]
        else:
            cases = list(EvaluationCase.objects.filter(is_active=True, workspace_key=workspace_key)[:limit])

        runs = [self._run_case(case) for case in cases]
        passed_count = sum(1 for run in runs if run.passed)
        return Response(
            {
                "total": len(runs),
                "passed": passed_count,
                "pass_rate": round(passed_count / len(runs), 2) if runs else 0,
                "runs": [serialize_evaluation_run(run) for run in runs],
            }
        )

    def _run_case(self, case: EvaluationCase) -> EvaluationRun:
        started_at = time.perf_counter()
        try:
            response = MultiAgentSupervisor(Path(settings.BASE_DIR).parent).chat(case.question)
            response_data = response.to_dict()
            observation = create_agent_observation(
                conversation=None,
                agent_run=None,
                input_message=case.question,
                workspace_key=case.workspace_key,
                response_data=response_data,
                latency_ms=round((time.perf_counter() - started_at) * 1000),
            )
            metrics = evaluate_answer(case, response_data, observation)
            passed = (
                metrics["answer_correctness"] >= 0.6
                and metrics["faithfulness"] >= 0.7
                and metrics["tool_success_rate"] >= 0.8
            )
            return EvaluationRun.objects.create(
                case=case,
                workspace_key=case.workspace_key,
                observation=observation,
                answer=response_data.get("answer", ""),
                metrics=metrics,
                passed=passed,
            )
        except Exception as exc:
            observation = create_agent_observation(
                conversation=None,
                agent_run=None,
                input_message=case.question,
                workspace_key=case.workspace_key,
                latency_ms=round((time.perf_counter() - started_at) * 1000),
                failure_reason=str(exc),
            )
            return EvaluationRun.objects.create(
                case=case,
                workspace_key=case.workspace_key,
                observation=observation,
                answer="",
                metrics={
                    "answer_correctness": 0,
                    "faithfulness": 0,
                    "citation_accuracy": 0,
                    "latency_ms": observation.latency_ms,
                    "tool_success_rate": 0,
                    "failure_reason": str(exc),
                },
                passed=False,
            )


class KnowledgeBaseListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        get_default_knowledge_base()
        knowledge_bases = KnowledgeBase.objects.filter(workspace_key=get_workspace_key(request))
        return Response([serialize_knowledge_base(item) for item in knowledge_bases])

    def post(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        name = str(request.data.get("name", "")).strip()
        if not name:
            return Response({"detail": "name is required"}, status=status.HTTP_400_BAD_REQUEST)

        knowledge_base, created = KnowledgeBase.objects.get_or_create(
            name=name,
            defaults={
                "workspace_key": get_workspace_key(request),
                "description": str(request.data.get("description", "")).strip(),
            },
        )
        if not created:
            knowledge_base.description = str(request.data.get("description", knowledge_base.description)).strip()
            knowledge_base.save(update_fields=["description", "updated_at"])
        return Response(serialize_knowledge_base(knowledge_base), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class KnowledgeBaseDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def delete(self, request, pk: int):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        knowledge_base = get_object_or_404(KnowledgeBase, pk=pk, workspace_key=get_workspace_key(request))
        approval = ApprovalRequest.objects.create(
            action=ApprovalRequest.Action.DELETE_KNOWLEDGE_BASE,
            workspace_key=get_workspace_key(request),
            title=f"删除知识库：{knowledge_base.name}",
            description="删除知识库会级联删除其中的文档、切片和向量索引。",
            payload={"knowledge_base_id": knowledge_base.id, "name": knowledge_base.name},
            requester=str(request.data.get("requester", "operator")).strip() if hasattr(request, "data") else "operator",
        )
        return approval_required_response(approval)


class DocumentListUploadView(APIView):
    authentication_classes = []
    permission_classes = []
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        knowledge_base_id = request.query_params.get("knowledge_base_id")
        documents = Document.objects.select_related("knowledge_base").filter(workspace_key=get_workspace_key(request))
        if knowledge_base_id:
            documents = documents.filter(knowledge_base_id=knowledge_base_id)
        return Response([serialize_document(document) for document in documents[:50]])

    def post(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "file is required"}, status=status.HTTP_400_BAD_REQUEST)

        suffix = Path(upload.name).suffix.lower()
        if suffix not in {".md", ".markdown", ".txt", ".pdf"}:
            return Response(
                {"detail": "only Markdown, txt and PDF files are supported"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        knowledge_base_id = request.data.get("knowledge_base_id")
        if knowledge_base_id:
            knowledge_base = get_object_or_404(KnowledgeBase, pk=knowledge_base_id, workspace_key=get_workspace_key(request))
        else:
            knowledge_base = get_default_knowledge_base()

        title = str(request.data.get("title") or Path(upload.name).stem).strip()
        document = Document.objects.create(
            knowledge_base=knowledge_base,
            workspace_key=get_workspace_key(request),
            title=title,
            source_file=upload,
            content_type=getattr(upload, "content_type", "") or suffix.lstrip("."),
        )
        document = ingest_document(document)
        return Response(serialize_document(document), status=status.HTTP_201_CREATED)


class DocumentDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def delete(self, request, pk: int):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        document = get_object_or_404(Document, pk=pk, workspace_key=get_workspace_key(request))
        approval = ApprovalRequest.objects.create(
            action=ApprovalRequest.Action.DELETE_DOCUMENT,
            workspace_key=get_workspace_key(request),
            title=f"删除文档：{document.title}",
            description="删除文档会删除对应切片、embedding 记录，并影响知识库检索结果。",
            payload={"document_id": document.id, "title": document.title},
            requester=str(request.data.get("requester", "operator")).strip() if hasattr(request, "data") else "operator",
        )
        return approval_required_response(approval)


class DocumentReindexView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, pk: int):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        document = get_object_or_404(Document, pk=pk, workspace_key=get_workspace_key(request))
        document = ingest_document(document)
        return Response(serialize_document(document))


class KnowledgeSearchView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        query = str(request.data.get("query", "")).strip()
        if not query:
            return Response({"detail": "query is required"}, status=status.HTTP_400_BAD_REQUEST)

        knowledge_base_id = request.data.get("knowledge_base_id")
        if knowledge_base_id:
            get_object_or_404(KnowledgeBase, pk=knowledge_base_id, workspace_key=get_workspace_key(request))
        limit = request.data.get("limit", 5)
        try:
            limit = max(1, min(int(limit), 10))
        except (TypeError, ValueError):
            limit = 5

        results = search_knowledge_base(
            query,
            knowledge_base_id=int(knowledge_base_id) if knowledge_base_id else None,
            limit=limit,
        )
        return Response(
            [
                {
                    "document_id": item.document_id,
                    "document_title": item.document_title,
                    "chunk_id": item.chunk_id,
                    "chunk_index": item.chunk_index,
                    "content": item.content,
                    "score": item.score,
                }
                for item in results
            ]
        )


class ApprovalRequestListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        status_filter = request.query_params.get("status", "pending")
        approvals = ApprovalRequest.objects.filter(workspace_key=get_workspace_key(request))
        if status_filter != "all":
            approvals = approvals.filter(status=status_filter)
        return Response([serialize_approval_request(approval) for approval in approvals[:100]])


class ApprovalRequestDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, pk: int):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        approval = get_object_or_404(ApprovalRequest, pk=pk, workspace_key=get_workspace_key(request))
        decision = str(request.data.get("decision", "")).strip().lower()
        reviewer = str(request.data.get("reviewer", "admin")).strip()
        note = str(request.data.get("note", "")).strip()

        if approval.status != ApprovalRequest.Status.PENDING:
            return Response(
                {"detail": "approval request is no longer pending"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if decision not in {"approve", "reject"}:
            return Response({"detail": "decision must be approve or reject"}, status=status.HTTP_400_BAD_REQUEST)

        approval.reviewer = reviewer
        approval.review_note = note
        approval.reviewed_at = timezone.now()

        if decision == "reject":
            approval.status = ApprovalRequest.Status.REJECTED
            approval.result = "人工审批已拒绝，敏感操作未执行。"
            approval.save(update_fields=["reviewer", "review_note", "reviewed_at", "status", "result"])
            return Response(serialize_approval_request(approval))

        try:
            approval.result = execute_approval_request(approval)
            approval.status = ApprovalRequest.Status.EXECUTED
            approval.executed_at = timezone.now()
        except Exception as exc:
            approval.result = str(exc)
            approval.status = ApprovalRequest.Status.FAILED
        approval.save(update_fields=["reviewer", "review_note", "reviewed_at", "status", "result", "executed_at"])
        return Response(serialize_approval_request(approval))


class MCPToolListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        ensure_default_mcp_tools()
        tools = MCPTool.objects.filter(workspace_key=get_workspace_key(request))
        return Response([serialize_mcp_tool(tool) for tool in tools])


class MCPToolDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def patch(self, request, pk: int):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        tool = get_object_or_404(MCPTool, pk=pk, workspace_key=get_workspace_key(request))
        if "is_enabled" in request.data:
            tool.is_enabled = bool(request.data["is_enabled"])
        if "requires_approval" in request.data:
            tool.requires_approval = bool(request.data["requires_approval"])
        if "permission_scope" in request.data:
            tool.permission_scope = str(request.data["permission_scope"]).strip()
        tool.save(update_fields=["is_enabled", "requires_approval", "permission_scope", "updated_at"])
        return Response(serialize_mcp_tool(tool))


class MCPToolExecuteView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, pk: int):
        from agent.mcp_tools import LocalMCPToolRunner

        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        tool = get_object_or_404(MCPTool, pk=pk, workspace_key=get_workspace_key(request))
        query = str(request.data.get("query", "")).strip()
        if not tool.is_enabled:
            return Response({"detail": "tool is disabled"}, status=status.HTTP_400_BAD_REQUEST)
        if tool.requires_approval:
            approval = ApprovalRequest.objects.create(
                action=ApprovalRequest.Action.EXECUTE_SQL,
                workspace_key=get_workspace_key(request),
                title=f"执行 MCP 工具：{tool.display_name}",
                description=f"工具权限范围：{tool.permission_scope}",
                payload={"tool_id": tool.id, "tool_name": tool.name, "query": query},
                requester=str(request.data.get("requester", "operator")).strip(),
            )
            return approval_required_response(approval)

        execution = LocalMCPToolRunner(Path(settings.BASE_DIR).parent).run(tool.name, query)
        tool.last_used_at = timezone.now()
        tool.save(update_fields=["last_used_at", "updated_at"])
        return Response(
            {
                "tool": serialize_mcp_tool(tool),
                "input": execution.input,
                "output": execution.output,
            }
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

    if approval.action == ApprovalRequest.Action.EXECUTE_SQL and payload.get("tool_name"):
        from agent.mcp_tools import LocalMCPToolRunner

        tool = get_object_or_404(MCPTool, pk=payload.get("tool_id"), workspace_key=approval.workspace_key)
        if not tool.is_enabled:
            raise ValueError(f"MCP 工具已禁用：{tool.display_name}")
        execution = LocalMCPToolRunner(Path(settings.BASE_DIR).parent).run(tool.name, str(payload.get("query", "")))
        tool.last_used_at = timezone.now()
        tool.save(update_fields=["last_used_at", "updated_at"])
        return f"MCP 工具已执行：{tool.display_name}\n\n{execution.output}"

    return "该审批类型当前只记录审批结果，未绑定自动执行器。"


class BlogArticleListCreateView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        articles = BlogArticle.objects.select_related("category", "knowledge_document").prefetch_related("tags").filter(
            workspace_key=get_workspace_key(request)
        )
        status_filter = request.query_params.get("status", BlogArticle.Status.PUBLISHED)
        if status_filter != "all":
            articles = articles.filter(status=status_filter)

        category = request.query_params.get("category")
        tag = request.query_params.get("tag")
        query = str(request.query_params.get("q", "")).strip()
        if category:
            articles = articles.filter(category__slug=category)
        if tag:
            articles = articles.filter(tags__slug=tag)
        if query:
            articles = articles.filter(Q(title__icontains=query) | Q(summary__icontains=query) | Q(content__icontains=query))

        return Response([serialize_article(article) for article in articles.distinct()[:50]])

    def post(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        title = str(request.data.get("title", "")).strip()
        content = str(request.data.get("content", "")).strip()
        if not title or not content:
            return Response({"detail": "title and content are required"}, status=status.HTTP_400_BAD_REQUEST)

        article = BlogArticle.objects.create(
            title=title,
            workspace_key=get_workspace_key(request),
            slug=unique_slug(BlogArticle, request.data.get("slug") or title, max_length=200),
            summary=str(request.data.get("summary", "")).strip(),
            content=content,
            category=get_or_create_category(request.data.get("category")),
            status=str(request.data.get("status", BlogArticle.Status.DRAFT)),
        )
        set_article_tags(article, request.data.get("tags", []))
        if article.status == BlogArticle.Status.PUBLISHED or request.data.get("publish"):
            article.status = BlogArticle.Status.DRAFT
            article.save(update_fields=["status", "updated_at"])
            approval = ApprovalRequest.objects.create(
                action=ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE,
                workspace_key=get_workspace_key(request),
                title=f"发布博客：{article.title}",
                description="发布博客会公开文章，并将文章内容写入知识库供 Agent 检索。",
                payload={"article_slug": article.slug, "article_id": article.id, "title": article.title},
                requester=str(request.data.get("requester", "blog-editor")).strip(),
            )
            return Response(
                {
                    "approval_required": True,
                    "article": serialize_article(article, include_content=True),
                    "approval": serialize_approval_request(approval),
                    "detail": "文章已保存为草稿，发布请求已进入人工审批。",
                },
                status=status.HTTP_202_ACCEPTED,
            )
        return Response(serialize_article(article, include_content=True), status=status.HTTP_201_CREATED)


class BlogImageUploadView(APIView):
    authentication_classes = []
    permission_classes = []
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        upload = request.FILES.get("image")
        if upload is None:
            return Response({"detail": "image is required"}, status=status.HTTP_400_BAD_REQUEST)

        if not upload.content_type.startswith("image/"):
            return Response({"detail": "only image files are supported"}, status=status.HTTP_400_BAD_REQUEST)

        suffix = Path(upload.name).suffix.lower() or ".png"
        if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}:
            return Response({"detail": "unsupported image format"}, status=status.HTTP_400_BAD_REQUEST)

        max_size = 5 * 1024 * 1024
        if upload.size > max_size:
            return Response({"detail": "image must be smaller than 5MB"}, status=status.HTTP_400_BAD_REQUEST)

        filename = f"blog/{uuid4().hex}{suffix}"
        saved_path = default_storage.save(filename, ContentFile(upload.read()))
        media_url = f"/{settings.MEDIA_URL.lstrip('/')}{saved_path}"
        image_url = request.build_absolute_uri(media_url)
        return Response(
            {
                "url": image_url,
                "markdown": f"![{Path(upload.name).stem}]({image_url})",
            },
            status=status.HTTP_201_CREATED,
        )


class BlogArticleDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, slug: str):
        article = get_object_or_404(
            BlogArticle.objects.select_related("category", "knowledge_document").prefetch_related("tags"),
            slug=slug,
            workspace_key=get_workspace_key(request),
        )
        article.view_count += 1
        article.save(update_fields=["view_count", "updated_at"])
        return Response(serialize_article(article, include_content=True))

    def patch(self, request, slug: str):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        article = get_object_or_404(BlogArticle, slug=slug, workspace_key=get_workspace_key(request))
        if "title" in request.data:
            article.title = str(request.data["title"]).strip()
        if "summary" in request.data:
            article.summary = str(request.data["summary"]).strip()
        if "content" in request.data:
            article.content = str(request.data["content"]).strip()
        if "category" in request.data:
            article.category = get_or_create_category(request.data.get("category"))
        if "status" in request.data:
            article.status = str(request.data["status"])
        article.save()
        if "tags" in request.data:
            set_article_tags(article, request.data.get("tags", []))
        if article.status == BlogArticle.Status.PUBLISHED or request.data.get("publish"):
            article.status = BlogArticle.Status.DRAFT
            article.save(update_fields=["status", "updated_at"])
            approval = ApprovalRequest.objects.create(
                action=ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE,
                workspace_key=get_workspace_key(request),
                title=f"发布博客：{article.title}",
                description="发布博客会公开文章，并将文章内容写入知识库供 Agent 检索。",
                payload={"article_slug": article.slug, "article_id": article.id, "title": article.title},
                requester=str(request.data.get("requester", "blog-editor")).strip(),
            )
            return Response(
                {
                    "approval_required": True,
                    "article": serialize_article(article, include_content=True),
                    "approval": serialize_approval_request(approval),
                    "detail": "发布请求已进入人工审批。",
                },
                status=status.HTTP_202_ACCEPTED,
            )
        return Response(serialize_article(article, include_content=True))

    @transaction.atomic
    def delete(self, request, slug: str):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        article = get_object_or_404(BlogArticle, slug=slug, workspace_key=get_workspace_key(request))
        approval = ApprovalRequest.objects.create(
            action=ApprovalRequest.Action.DELETE_BLOG_ARTICLE,
            workspace_key=get_workspace_key(request),
            title=f"删除博客：{article.title}",
            description="删除博客会移除文章，并删除它同步到知识库的文档。",
            payload={"article_slug": article.slug, "article_id": article.id, "title": article.title},
            requester=str(request.data.get("requester", "blog-editor")).strip() if hasattr(request, "data") else "blog-editor",
        )
        return approval_required_response(approval)


class BlogArticlePublishView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, slug: str):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        article = get_object_or_404(BlogArticle, slug=slug, workspace_key=get_workspace_key(request))
        approval = ApprovalRequest.objects.create(
            action=ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE,
            workspace_key=get_workspace_key(request),
            title=f"发布博客：{article.title}",
            description="发布博客会公开文章，并将文章内容写入知识库供 Agent 检索。",
            payload={"article_slug": article.slug, "article_id": article.id, "title": article.title},
            requester=str(request.data.get("requester", "blog-editor")).strip() if hasattr(request, "data") else "blog-editor",
        )
        return approval_required_response(approval)


class BlogCategoryListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        categories = ArticleCategory.objects.all()
        return Response([serialize_category(category) for category in categories])


class BlogTagListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        tags = ArticleTag.objects.all()
        return Response([serialize_tag(tag) for tag in tags])


class BlogArchiveView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        articles = BlogArticle.objects.filter(
            status=BlogArticle.Status.PUBLISHED,
            workspace_key=get_workspace_key(request),
        ).order_by("-published_at")
        archive: dict[str, list[dict]] = {}
        for article in articles:
            key = article.published_at.strftime("%Y-%m") if article.published_at else "未发布"
            archive.setdefault(key, []).append(serialize_article(article))
        return Response([{"month": month, "articles": items} for month, items in archive.items()])


class BlogAboutView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response(
            {
                "title": "关于这个知识型博客",
                "content": (
                    "这个博客不是普通 CMS，而是个人技术经历和 Agent 知识库的入口。"
                    "文章发布后会自动进入知识库，访客不仅能阅读文章，也能向 Agent 询问项目经历、"
                    "架构思路、论文方向和技术栈选择。"
                ),
                "highlights": [
                    "Vue 3 + Django 的全栈项目",
                    "LangChain / LangGraph Agentic RAG",
                    "博客文章自动向量化并进入个人知识库",
                    "可交互的个人技术简历",
                ],
            }
        )


class BlogAgentChatView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        message = str(request.data.get("message", "")).strip()
        if not message:
            return Response({"detail": "message is required"}, status=status.HTTP_400_BAD_REQUEST)
        if len(message) > 800:
            return Response({"detail": "message must be shorter than 800 characters"}, status=status.HTTP_400_BAD_REQUEST)

        session = self._get_or_create_session(request)
        if session.is_blocked:
            return Response({"detail": "this visitor session is blocked"}, status=status.HTTP_403_FORBIDDEN)
        if self._is_rate_limited(session):
            return Response(
                {"detail": "提问太频繁了，请稍后再试。"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        BlogAgentMessage.objects.create(
            session=session,
            role=BlogAgentMessage.Role.USER,
            content=message,
        )

        agent = PublicBlogAgent(Path(settings.BASE_DIR).parent)
        answer = agent.answer(message)
        payload = answer.to_dict()

        if answer.blocked:
            BlogAgentSecurityEvent.objects.create(
                session=session,
                question=message,
                reason=answer.block_reason,
                ip_hash=session.ip_hash,
            )

        agent_message = BlogAgentMessage.objects.create(
            session=session,
            role=BlogAgentMessage.Role.AGENT,
            content=answer.answer,
            sources=payload["sources"],
            trace=answer.trace,
            token_usage=answer.token_usage,
        )
        session.save(update_fields=["updated_at"])

        return Response(
            {
                **payload,
                "session_key": session.session_key,
                "message": serialize_blog_agent_message(agent_message),
            }
        )

    def get(self, request):
        session_key = str(request.query_params.get("session_key", "")).strip()
        if not session_key:
            return Response({"messages": []})

        session = get_object_or_404(BlogAgentSession, session_key=session_key)
        messages = session.messages.all().order_by("-id")[:20]
        return Response(
            {
                "session_key": session.session_key,
                "messages": [serialize_blog_agent_message(message) for message in reversed(messages)],
            }
        )

    def _get_or_create_session(self, request) -> BlogAgentSession:
        session_key = str(request.data.get("session_key", "")).strip()
        if not session_key:
            session_key = uuid4().hex

        session, _ = BlogAgentSession.objects.get_or_create(
            session_key=session_key,
            defaults={
                "visitor_label": "匿名访客",
                "ip_hash": request_ip_hash(request),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:1000],
            },
        )
        return session

    def _is_rate_limited(self, session: BlogAgentSession) -> bool:
        since = timezone.now() - timedelta(seconds=BLOG_AGENT_RATE_WINDOW_SECONDS)
        recent_count = session.messages.filter(
            role=BlogAgentMessage.Role.USER,
            created_at__gte=since,
        ).count()
        return recent_count >= BLOG_AGENT_RATE_LIMIT


class BlogCommentCreateView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, slug: str):
        article = get_object_or_404(BlogArticle, slug=slug, workspace_key=get_workspace_key(request))
        comments = article.comments.filter(is_approved=True)
        return Response(
            [
                {
                    "id": comment.id,
                    "author_name": comment.author_name,
                    "content": comment.content,
                    "created_at": comment.created_at.isoformat(),
                }
                for comment in comments
            ]
        )

    def post(self, request, slug: str):
        article = get_object_or_404(BlogArticle, slug=slug, workspace_key=get_workspace_key(request))
        author_name = str(request.data.get("author_name", "")).strip()
        content = str(request.data.get("content", "")).strip()
        if not author_name or not content:
            return Response({"detail": "author_name and content are required"}, status=status.HTTP_400_BAD_REQUEST)
        comment = BlogComment.objects.create(article=article, author_name=author_name, content=content)
        return Response(
            {
                "id": comment.id,
                "author_name": comment.author_name,
                "content": comment.content,
                "created_at": comment.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )
