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

from ..exceptions import ErrorCode
from ..models import BlogAgentMessage, BlogAgentSecurityEvent, BlogAgentSession
from ..serializers import serialize_blog_agent_message
from ..services.blog_agent import PublicBlogAgent
from .common import BLOG_AGENT_RATE_LIMIT, BLOG_AGENT_RATE_WINDOW_SECONDS, error_response, request_ip_hash


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
        answer = agent.answer(message, history=history)
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
