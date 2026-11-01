"""会话历史：列表、详情与消息游标分页。"""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Conversation, UserProfile
from ..serializers import serialize_conversation
from .common import get_conversation_owner, get_message_limit, get_workspace_key, require_roles

DEFAULT_CONVERSATION_LIMIT = 20

MAX_CONVERSATION_LIMIT = 50


def get_conversation_pagination(request) -> tuple[int, int]:
    """解析会话列表分页参数。

    limit 默认 20、上限 50；非法值回退默认，负数 limit 被钳制为 1。
    offset 默认 0，非法或负数归 0。返回值保证切片永远是有效区间。
    """
    try:
        limit = int(request.query_params.get("limit", DEFAULT_CONVERSATION_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_CONVERSATION_LIMIT
    try:
        offset = int(request.query_params.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    return max(1, min(limit, MAX_CONVERSATION_LIMIT)), max(0, offset)


class ConversationListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        query = str(request.query_params.get("q", "")).strip()
        project_filter = request.query_params.get("project")
        limit, offset = get_conversation_pagination(request)
        conversations = Conversation.objects.filter(
            workspace_key=get_workspace_key(request),
            owner_username=get_conversation_owner(request),
        )
        # project=none 表示只看未分组对话；project=<id> 只看该项目
        if project_filter == "none":
            conversations = conversations.filter(project__isnull=True)
        elif project_filter:
            conversations = conversations.filter(project_id=project_filter)
        if query:
            conversations = conversations.filter(
                Q(title__icontains=query) | Q(messages__content__icontains=query)
            ).distinct()

        results = []
        for conversation in conversations[offset : offset + limit]:
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
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        conversation = get_object_or_404(
            Conversation,
            pk=pk,
            workspace_key=get_workspace_key(request),
            owner_username=get_conversation_owner(request),
        )
        limit = get_message_limit(request)
        before = request.query_params.get("before")
        anchor = request.query_params.get("anchor")

        messages_queryset = conversation.messages.all()
        has_more_after = False

        if anchor:
            anchor_message = get_object_or_404(messages_queryset, pk=anchor)
            before_count = max(1, limit // 2)
            after_count = max(0, limit - before_count)
            before_messages = list(messages_queryset.filter(id__lte=anchor_message.id).order_by("-id")[:before_count])
            after_messages = list(messages_queryset.filter(id__gt=anchor_message.id).order_by("id")[:after_count])
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
