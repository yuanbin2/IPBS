from rest_framework import serializers

from ..models import ApprovalRequest, MCPTool


class ApprovalRequestSerializer(serializers.ModelSerializer):
    action_label = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = ApprovalRequest
        fields = [
            "id", "action", "action_label", "title", "description", "payload",
            "status", "requester", "reviewer", "review_note", "result",
            "created_at", "reviewed_at", "executed_at",
        ]


class MCPToolSerializer(serializers.ModelSerializer):
    health_status_label = serializers.CharField(source="get_health_status_display", read_only=True)

    class Meta:
        model = MCPTool
        fields = [
            "id", "name", "display_name", "description", "category",
            "permission_scope", "is_enabled", "requires_approval", "config",
            "last_used_at", "call_count", "success_count",
            "health_status", "health_status_label", "last_health_check", "health_message",
            "created_at", "updated_at",
        ]


def serialize_approval_request(instance):
    return ApprovalRequestSerializer(instance).data


def serialize_mcp_tool(instance):
    return MCPToolSerializer(instance).data
