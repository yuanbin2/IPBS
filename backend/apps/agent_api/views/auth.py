import os
from pathlib import Path

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from agent.security import issue_jwt_pair, security_enforced

from ..exceptions import ErrorCode
from ..models import SecurityAuditEvent, UserProfile
from ..serializers import serialize_security_audit_event, serialize_user_profile
from .common import (
    audit_security_event,
    env_file_is_git_tracked,
    error_response,
    get_workspace_key,
    require_roles,
    serialize_security_context,
)


class AuthLoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        username = str(request.data.get("username", "")).strip()
        password = str(request.data.get("password", ""))
        if not username or not password:
            return error_response(
                "username and password are required", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(request, username=username, password=password)
        if user is None:
            return error_response("invalid credentials", ErrorCode.INVALID_CREDENTIALS, status.HTTP_401_UNAUTHORIZED)

        tokens = issue_jwt_pair(user)
        profile = user.agent_profile
        audit_security_event(
            request,
            SecurityAuditEvent.EventType.LOGIN,
            "login succeeded",
            {"username": username, "role": profile.role},
            actor=user.username,
            role=profile.role,
            workspace_key=profile.workspace_key,
        )
        return Response(
            {
                "token": tokens["access"],
                "access": tokens["access"],
                "refresh": tokens["refresh"],
                "user": serialize_user_profile(profile),
                "session": {
                    "actor": user.username,
                    "role": profile.role,
                    "workspace_key": profile.workspace_key,
                    "authenticated": True,
                    "security_enforced": security_enforced(),
                },
            }
        )


def _set_refresh_cookie(response, token):
    response.set_cookie(
        settings.JWT_REFRESH_COOKIE_NAME,
        token,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        path=settings.JWT_REFRESH_COOKIE_PATH,
        secure=settings.CSRF_COOKIE_SECURE,
        httponly=True,
        samesite=settings.JWT_REFRESH_COOKIE_SAMESITE,
    )
    return response


def _clear_refresh_cookie(response):
    response.delete_cookie(
        settings.JWT_REFRESH_COOKIE_NAME,
        path=settings.JWT_REFRESH_COOKIE_PATH,
        samesite=settings.JWT_REFRESH_COOKIE_SAMESITE,
    )
    return response


class AuthCsrfView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"csrfToken": get_token(request)})


@method_decorator(csrf_protect, name="dispatch")
class AuthCookieLoginView(AuthLoginView):
    def post(self, request):
        response = super().post(request)
        if response.status_code == status.HTTP_200_OK:
            refresh = response.data.pop("refresh")
            _set_refresh_cookie(response, refresh)
        return response


@method_decorator(csrf_protect, name="dispatch")
class AuthCookieRefreshView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        refresh = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
        if not refresh:
            return error_response(
                "refresh cookie is required", ErrorCode.INVALID_CREDENTIALS, status.HTTP_401_UNAUTHORIZED
            )
        serializer = TokenRefreshSerializer(data={"refresh": refresh})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError:
            return error_response("invalid refresh cookie", ErrorCode.INVALID_CREDENTIALS, status.HTTP_401_UNAUTHORIZED)
        response = Response({"access": serializer.validated_data["access"]})
        return _set_refresh_cookie(response, serializer.validated_data["refresh"])


@method_decorator(csrf_protect, name="dispatch")
class AuthCookieUpgradeView(APIView):
    """Exchange one legacy browser refresh token for an HttpOnly cookie once."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        legacy_refresh = request.data.get("refresh")
        if not isinstance(legacy_refresh, str) or not legacy_refresh:
            return error_response(
                "refresh token is required", ErrorCode.INVALID_CREDENTIALS, status.HTTP_401_UNAUTHORIZED
            )
        serializer = TokenRefreshSerializer(data={"refresh": legacy_refresh})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError:
            return error_response("invalid refresh token", ErrorCode.INVALID_CREDENTIALS, status.HTTP_401_UNAUTHORIZED)
        response = Response({"access": serializer.validated_data["access"]})
        return _set_refresh_cookie(response, serializer.validated_data["refresh"])


@method_decorator(csrf_protect, name="dispatch")
class AuthCookieLogoutView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        refresh = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
        if refresh:
            try:
                RefreshToken(refresh).blacklist()
            except TokenError:
                # The cookie may already be expired or revoked; clearing it is idempotent.
                pass
        return _clear_refresh_cookie(Response(status=status.HTTP_204_NO_CONTENT))


class AuthRegisterView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        username = str(request.data.get("username", "")).strip()
        password = str(request.data.get("password", ""))
        if not username or not password:
            return error_response(
                "username and password are required", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST
            )
        if len(password) < 8:
            return error_response(
                "password must be at least 8 characters", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            return error_response("username already exists", ErrorCode.CONFLICT, status.HTTP_400_BAD_REQUEST)

        # Registration is self-service only for visitor accounts. Privileged
        # roles and workspace membership must be granted by an administrator.
        role = UserProfile.Role.VISITOR
        workspace_key = "default"
        user = User.objects.create_user(username=username, password=password)
        profile, _ = UserProfile.objects.update_or_create(
            user=user,
            defaults={"role": role, "workspace_key": workspace_key},
        )
        tokens = issue_jwt_pair(user)
        audit_security_event(
            request,
            SecurityAuditEvent.EventType.LOGIN,
            "registration succeeded",
            {"username": username, "role": role, "workspace_key": workspace_key},
            actor=user.username,
            role=profile.role,
            workspace_key=profile.workspace_key,
        )
        return Response(
            {
                "token": tokens["access"],
                "access": tokens["access"],
                "refresh": tokens["refresh"],
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


@method_decorator(csrf_protect, name="dispatch")
class AuthCookieRegisterView(AuthRegisterView):
    def post(self, request):
        response = super().post(request)
        if response.status_code == status.HTTP_201_CREATED:
            refresh = response.data.pop("refresh")
            _set_refresh_cookie(response, refresh)
        return response


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
