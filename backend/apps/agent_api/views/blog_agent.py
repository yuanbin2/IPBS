"""访客博客 Agent：公开检索 + 限流 + 安全拦截。"""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.security import redact_sensitive_output

from ..exceptions import ErrorCode
from ..models import BlogAgentMessage, BlogAgentSecurityEvent, BlogAgentSession
from ..serializers import serialize_blog_agent_message
from ..services.blog_agent import PublicBlogAgent
from .common import BLOG_AGENT_RATE_LIMIT, BLOG_AGENT_RATE_WINDOW_SECONDS, error_response, request_ip_hash


def _redact_public_payload(value):
    """Keep model output, source snippets and traces safe before saving or returning them."""
    if isinstance(value, str):
        return redact_sensitive_output(value)[0]
    if isinstance(value, list):
        return [_redact_public_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_public_payload(item) for key, item in value.items()}
    return value


# GET 历史分页：默认 10 条、上限 50（与 conversations 的 limit 风格一致）。
DEFAULT_BLOG_AGENT_HISTORY_LIMIT = 10
MAX_BLOG_AGENT_HISTORY_LIMIT = 50


def get_blog_agent_history_limit(request) -> int:
    """解析历史消息条数；非法值回退默认，负数钳制为 1。"""
    try:
        limit = int(request.query_params.get("limit", DEFAULT_BLOG_AGENT_HISTORY_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_BLOG_AGENT_HISTORY_LIMIT
    return max(1, min(limit, MAX_BLOG_AGENT_HISTORY_LIMIT))


class BlogAgentChatView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        message = str(request.data.get("message", "")).strip()
        if not message:
            return error_response("message is required", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST)
        if len(message) > 800:
            return error_response(
                "message must be shorter than 800 characters", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )

        session = self._get_or_create_session(request)
        if session.is_blocked:
            return error_response("this visitor session is blocked", ErrorCode.FORBIDDEN, status.HTTP_403_FORBIDDEN)
        if self._is_rate_limited(session):
            return error_response(
                "提问太频繁了，请稍后再试。", ErrorCode.RATE_LIMITED, status.HTTP_429_TOO_MANY_REQUESTS
            )

        previous_messages = list(session.messages.order_by("-id")[:10])
        history = [{"role": item.role, "content": item.content} for item in reversed(previous_messages)]

        BlogAgentMessage.objects.create(
            session=session,
            role=BlogAgentMessage.Role.USER,
            content=message,
        )

        agent = PublicBlogAgent(Path(settings.BASE_DIR).parent)
        rag_source = str(request.data.get("rag_source", "legacy")).strip().lower()
        if rag_source not in ("legacy", "ragagent"):
            rag_source = "legacy"
        degraded = False
        degraded_reason = ""
        if rag_source == "ragagent":
            # B051：RAG-Agent 外部知识源；任何失败降级回站内检索（fail-open）
            from dataclasses import replace
            from ..services.rag_agent_client import RagAgentError, answer_via_rag_agent
            try:
                answer = answer_via_rag_agent(message)
            except RagAgentError as exc:
                # 降级回站内检索；BlogAgentAnswer 是 frozen dataclass，
                # 用 replace 生成带降级 trace 的新实例
                legacy = agent.answer(message, history=history)
                answer = replace(
                    legacy,
                    trace=[f"rag_agent -> degraded to legacy: {exc}", *legacy.trace],
                )
                # B052：降级必须对用户可见，附带原因短句
                degraded = True
                degraded_reason = str(exc)[:120]
        else:
            answer = agent.answer(message, history=history)
        payload = _redact_public_payload(answer.to_dict())
        payload["rag_source"] = rag_source
        # B052：透明性字段——实际生效来源 + 降级标记/原因
        payload["rag_source_effective"] = "ragagent" if (rag_source == "ragagent" and not degraded) else "legacy"
        payload["degraded"] = degraded
        payload["degraded_reason"] = degraded_reason

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
            content=payload["answer"],
            sources=payload["sources"],
            trace=payload["trace"],
            token_usage=payload["token_usage"],
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
            return Response({"messages": [], "has_more_before": False})

        session = get_object_or_404(BlogAgentSession, session_key=session_key)
        limit = get_blog_agent_history_limit(request)
        messages_queryset = session.messages.all()

        # before 为消息 id 游标：有则取该 id 之前（更早）的 limit 条，无则取最新 limit 条；均按 id 升序返回。
        raw_before = str(request.query_params.get("before", "")).strip()
        before_id: int | None = None
        if raw_before:
            try:
                before_id = int(raw_before)
            except (TypeError, ValueError):
                before_id = None
        if before_id is not None and before_id >= 1:
            messages = list(messages_queryset.filter(id__lt=before_id).order_by("-id")[:limit])
        else:
            messages = list(messages_queryset.order_by("-id")[:limit])
        messages = list(reversed(messages))
        has_more_before = messages_queryset.filter(id__lt=messages[0].id).exists() if messages else False
        return Response(
            {
                "session_key": session.session_key,
                "messages": [
                    _redact_public_payload(serialize_blog_agent_message(message)) for message in messages
                ],
                "has_more_before": has_more_before,
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
