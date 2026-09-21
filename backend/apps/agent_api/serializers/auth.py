from rest_framework import serializers

from ..models import SecurityAuditEvent, UserProfile


class UserProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = UserProfile
        fields = ["user_id", "username", "role", "workspace_key"]


class SecurityAuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityAuditEvent
        fields = [
            "id", "event_type", "actor", "role", "workspace_key", "path",
            "detail", "metadata", "created_at",
        ]


def serialize_user_profile(profile):
    return UserProfileSerializer(profile).data


def serialize_security_audit_event(event):
    return SecurityAuditEventSerializer(event).data
