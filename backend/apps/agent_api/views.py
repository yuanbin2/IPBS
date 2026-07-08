from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.simple_agent import SimpleToolCallingAgent

from .models import AgentRun, Conversation, Message


def serialize_message(message: Message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "tool_calls": message.tool_calls,
        "trace": message.trace,
        "token_usage": message.token_usage,
        "created_at": message.created_at.isoformat(),
    }


DEFAULT_MESSAGE_LIMIT = 30
MAX_MESSAGE_LIMIT = 50


def get_message_limit(request) -> int:
    try:
        limit = int(request.query_params.get("limit", DEFAULT_MESSAGE_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_MESSAGE_LIMIT
    return max(1, min(limit, MAX_MESSAGE_LIMIT))


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


class ConversationListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        query = str(request.query_params.get("q", "")).strip()
        conversations = Conversation.objects.all()
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
        conversation = get_object_or_404(Conversation, pk=pk)
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

    @transaction.atomic
    def post(self, request):
        message = str(request.data.get("message", "")).strip()
        if not message:
            return Response(
                {"detail": "message is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        conversation = self._get_or_create_conversation(request.data.get("conversation_id"), message)
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.USER,
            content=message,
        )

        project_root = Path(settings.BASE_DIR).parent
        agent = SimpleToolCallingAgent(project_root)
        response = agent.chat(message)
        response_data = response.to_dict()

        Message.objects.create(
            conversation=conversation,
            role=Message.Role.AGENT,
            content=response.answer,
            tool_calls=response_data["tool_calls"],
            trace=response.trace,
            token_usage=response.token_usage,
        )
        AgentRun.objects.create(
            conversation=conversation,
            input_message=message,
            route=response.route,
            tool_calls=response_data["tool_calls"],
            trace=response.trace,
            token_usage=response.token_usage,
        )

        conversation.save(update_fields=["updated_at"])
        return Response(
            {
                **response_data,
                "conversation": serialize_conversation(conversation),
            }
        )

    def _get_or_create_conversation(self, conversation_id, message: str) -> Conversation:
        if conversation_id:
            return get_object_or_404(Conversation, pk=conversation_id)

        title = message[:40]
        if len(message) > 40:
            title = f"{title}..."
        return Conversation.objects.create(title=title)
