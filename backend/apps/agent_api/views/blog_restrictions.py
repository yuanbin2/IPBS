"""Workspace-scoped comment/report restrictions and one appeal per restriction."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.security import get_or_create_profile, jwt_user_from_request, normalize_workspace_key

from ..exceptions import ErrorCode
from ..models import BlogInteractionRestriction, SecurityAuditEvent, UserProfile
from .common import error_response


def active_restriction_for(user, workspace_key: str):
    return (
        BlogInteractionRestriction.objects.filter(
            user=user,
            workspace_key=workspace_key,
            lifted_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .order_by("-created_at", "-id")
        .first()
    )


def _identity(request, *, admin=False):
    user = jwt_user_from_request(request)
    if user is None:
        return None, None, error_response("请先登录", ErrorCode.NOT_AUTHENTICATED, status.HTTP_401_UNAUTHORIZED)
    profile = get_or_create_profile(user)
    if admin and profile.role != UserProfile.Role.ADMIN:
        return None, None, error_response("无管理权限", ErrorCode.FORBIDDEN, status.HTTP_403_FORBIDDEN)
    return user, normalize_workspace_key(profile.workspace_key), None


def _serialize(restriction, *, admin=False):
    data = {
        "id": restriction.pk,
        "username": restriction.user.username,
        "reason": restriction.reason,
        "expires_at": restriction.expires_at.isoformat(),
        "created_at": restriction.created_at.isoformat(),
        "active": restriction.lifted_at is None and restriction.expires_at > timezone.now(),
        "appeal_status": restriction.appeal_status,
        "appeal_message": restriction.appeal_message,
    }
    if admin:
        data.update(
            {
                "imposed_by": restriction.imposed_by,
                "lifted_at": restriction.lifted_at.isoformat() if restriction.lifted_at else None,
                "appealed_at": restriction.appealed_at.isoformat() if restriction.appealed_at else None,
            }
        )
    return data


def _audit(request, actor, workspace_key, event_type, restriction, detail):
    SecurityAuditEvent.objects.create(
        event_type=event_type,
        actor=actor.username[:120],
        role=get_or_create_profile(actor).role,
        workspace_key=workspace_key,
        path=request.path[:240],
        detail=detail,
        metadata={"restriction_id": restriction.pk, "user_id": restriction.user_id},
    )


class MyBlogInteractionRestrictionView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        user, workspace_key, denied = _identity(request)
        if denied:
            return denied
        restriction = (
            BlogInteractionRestriction.objects.filter(user=user, workspace_key=workspace_key)
            .filter(Q(lifted_at__isnull=True, expires_at__gt=timezone.now()) | Q(appeal_status="pending"))
            .select_related("user")
            .order_by("-created_at", "-id")
            .first()
        )
        return Response({"restriction": _serialize(restriction) if restriction else None})


class BlogInteractionAppealView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        user, workspace_key, denied = _identity(request)
        if denied:
            return denied
        if not isinstance(request.data, dict):
            return error_response("invalid request", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        raw_message = request.data.get("message", "")
        message = raw_message.strip() if isinstance(raw_message, str) else ""
        if not 10 <= len(message) <= 1000:
            return error_response("申诉说明需为 10～1000 字", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            restriction = (
                BlogInteractionRestriction.objects.select_for_update()
                .filter(
                    user=user,
                    workspace_key=workspace_key,
                    lifted_at__isnull=True,
                    expires_at__gt=timezone.now(),
                )
                .order_by("-created_at", "-id")
                .first()
            )
            if restriction is None:
                return error_response("当前没有有效限制", ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND)
            if restriction.appeal_status != BlogInteractionRestriction.AppealStatus.NONE:
                return error_response("该限制已提交过申诉", ErrorCode.VALIDATION_ERROR, status.HTTP_409_CONFLICT)
            restriction.appeal_message = message
            restriction.appealed_at = timezone.now()
            restriction.appeal_status = BlogInteractionRestriction.AppealStatus.PENDING
            restriction.save(update_fields=["appeal_message", "appealed_at", "appeal_status"])
            _audit(
                request,
                user,
                workspace_key,
                SecurityAuditEvent.EventType.BLOG_INTERACTION_APPEALED,
                restriction,
                "appeal_submitted",
            )
        return Response(_serialize(restriction), status=status.HTTP_201_CREATED)


class BlogInteractionRestrictionListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        _user, workspace_key, denied = _identity(request, admin=True)
        if denied:
            return denied
        restrictions = (
            BlogInteractionRestriction.objects.filter(workspace_key=workspace_key)
            .select_related("user")
            .order_by("-created_at", "-id")[:100]
        )
        return Response([_serialize(item, admin=True) for item in restrictions])

    def post(self, request):
        actor, workspace_key, denied = _identity(request, admin=True)
        if denied:
            return denied
        if not isinstance(request.data, dict):
            return error_response("invalid request", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        raw_username = request.data.get("username", "")
        raw_reason = request.data.get("reason", "")
        username = raw_username.strip() if isinstance(raw_username, str) else ""
        reason = raw_reason.strip() if isinstance(raw_reason, str) else ""
        days = request.data.get("days")
        if not username or not 10 <= len(reason) <= 500 or type(days) is not int or not 1 <= days <= 30:
            return error_response(
                "请填写用户、10～500 字原因及 1～30 天期限", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )
        with transaction.atomic():
            profile = get_object_or_404(
                UserProfile.objects.select_for_update().select_related("user"),
                user__username=username,
                workspace_key=workspace_key,
                user__is_active=True,
            )
            if profile.user_id == actor.pk or profile.role == UserProfile.Role.ADMIN:
                return error_response("不能限制管理员账号", ErrorCode.FORBIDDEN, status.HTTP_403_FORBIDDEN)
            if active_restriction_for(profile.user, workspace_key):
                return error_response("该账号已有有效限制", ErrorCode.VALIDATION_ERROR, status.HTTP_409_CONFLICT)
            restriction = BlogInteractionRestriction.objects.create(
                user=profile.user,
                workspace_key=workspace_key,
                reason=reason,
                expires_at=timezone.now() + timedelta(days=days),
                imposed_by=actor.username[:120],
            )
            _audit(
                request,
                actor,
                workspace_key,
                SecurityAuditEvent.EventType.BLOG_INTERACTION_RESTRICTED,
                restriction,
                "restricted",
            )
        return Response(_serialize(restriction, admin=True), status=status.HTTP_201_CREATED)


class BlogInteractionRestrictionActionView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, restriction_id: int):
        actor, workspace_key, denied = _identity(request, admin=True)
        if denied:
            return denied
        if not isinstance(request.data, dict):
            return error_response("invalid request", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        action = str(request.data.get("action", "")).strip()
        if action not in {"lift", "accept_appeal", "uphold_appeal"}:
            return error_response("invalid action", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            restriction = get_object_or_404(
                BlogInteractionRestriction.objects.select_for_update().select_related("user"),
                pk=restriction_id,
                workspace_key=workspace_key,
            )
            if action == "lift":
                if restriction.lifted_at is not None:
                    return Response({**_serialize(restriction, admin=True), "changed": False})
                restriction.lifted_at = timezone.now()
                restriction.lifted_by = actor.username[:120]
                update_fields = ["lifted_at", "lifted_by"]
                if restriction.appeal_status == BlogInteractionRestriction.AppealStatus.PENDING:
                    restriction.appeal_status = BlogInteractionRestriction.AppealStatus.ACCEPTED
                    restriction.appeal_reviewed_by = actor.username[:120]
                    restriction.appeal_reviewed_at = restriction.lifted_at
                    update_fields.extend(["appeal_status", "appeal_reviewed_by", "appeal_reviewed_at"])
                restriction.save(update_fields=update_fields)
                event_type = SecurityAuditEvent.EventType.BLOG_INTERACTION_LIFTED
            else:
                if restriction.appeal_status != BlogInteractionRestriction.AppealStatus.PENDING:
                    return error_response("申诉不在待处理状态", ErrorCode.VALIDATION_ERROR, status.HTTP_409_CONFLICT)
                restriction.appeal_status = (
                    BlogInteractionRestriction.AppealStatus.ACCEPTED
                    if action == "accept_appeal"
                    else BlogInteractionRestriction.AppealStatus.UPHELD
                )
                restriction.appeal_reviewed_by = actor.username[:120]
                restriction.appeal_reviewed_at = timezone.now()
                update_fields = ["appeal_status", "appeal_reviewed_by", "appeal_reviewed_at"]
                if action == "accept_appeal":
                    restriction.lifted_at = restriction.appeal_reviewed_at
                    restriction.lifted_by = actor.username[:120]
                    update_fields.extend(["lifted_at", "lifted_by"])
                restriction.save(update_fields=update_fields)
                event_type = SecurityAuditEvent.EventType.BLOG_INTERACTION_APPEAL_REVIEWED
            _audit(request, actor, workspace_key, event_type, restriction, action)
        return Response({**_serialize(restriction, admin=True), "changed": True})
