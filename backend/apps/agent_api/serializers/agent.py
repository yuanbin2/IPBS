from rest_framework import serializers

from ..models import AgentObservation, Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id", "role", "content", "tool_calls", "sources", "trace",
            "token_usage", "created_at",
        ]


class AgentObservationSerializer(serializers.ModelSerializer):
    conversation_id = serializers.IntegerField(read_only=True, allow_null=True)
    agent_run_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = AgentObservation
        fields = [
            "id", "conversation_id", "agent_run_id", "input_message", "answer",
            "route", "selected_agent", "trace", "tool_calls", "sources",
            "token_usage", "latency_ms", "tool_success_rate", "status",
            "failure_reason", "langsmith_project", "langsmith_run_id", "created_at",
        ]


class ConversationSerializer(serializers.ModelSerializer):
    messages = serializers.SerializerMethodField()
    has_more_before = serializers.SerializerMethodField()
    has_more_after = serializers.SerializerMethodField()
    matched_message_id = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id", "title", "created_at", "updated_at", "matched_message_id",
            "messages", "has_more_before", "has_more_after",
        ]

    def get_messages(self, instance):
        if not self.context.get("include_messages"):
            return None
        messages = self.context.get("messages")
        selected = messages if messages is not None else instance.messages.all()
        return MessageSerializer(selected, many=True).data

    def get_has_more_before(self, _instance):
        return bool(self.context.get("has_more_before"))

    def get_has_more_after(self, _instance):
        return bool(self.context.get("has_more_after"))

    def get_matched_message_id(self, _instance):
        return self.context.get("matched_message_id")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.context.get("include_messages"):
            data.pop("messages", None)
            data.pop("has_more_before", None)
            data.pop("has_more_after", None)
        if not data.get("matched_message_id"):
            data.pop("matched_message_id", None)
        return data


def serialize_message(instance):
    return MessageSerializer(instance).data


def serialize_agent_observation(instance):
    return AgentObservationSerializer(instance).data


def serialize_conversation(
    instance,
    include_messages=False,
    messages=None,
    has_more_before=False,
    has_more_after=False,
    matched_message_id=None,
):
    return ConversationSerializer(
        instance,
        context={
            "include_messages": include_messages,
            "messages": messages,
            "has_more_before": has_more_before,
            "has_more_after": has_more_after,
            "matched_message_id": matched_message_id,
        },
    ).data
