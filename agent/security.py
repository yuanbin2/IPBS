"""Agent 请求的 JWT 身份、角色、工作区隔离和敏感信息过滤。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken


TOKEN_SALT = "knowledge-agent-auth"
TOKEN_MAX_AGE_SECONDS = 60 * 60 * 12
DEFAULT_WORKSPACE_KEY = "default"

SENSITIVE_INPUT_PATTERNS = [
    r"api\s*key",
    r"secret",
    r"password",
    r"数据库结构",
    r"后台信息",
    r"管理员信息",
    r"忽略.*规则",
    r"ignore.*previous",
    r"绕过.*审批",
    r"删除所有",
    r"drop\s+table",
]

SECRET_OUTPUT_PATTERNS = [
    r"sk-[A-Za-z0-9_\-]{12,}",
    r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[^'\"\s]{8,}",
]


@dataclass(frozen=True)
class SecurityContext:
    actor: str
    role: str
    workspace_key: str
    authenticated: bool


def issue_signed_token(user) -> str:
    """Return a standards-based short-lived JWT access token."""
    return str(RefreshToken.for_user(user).access_token)


def issue_jwt_pair(user) -> dict[str, str]:
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def context_from_request(request) -> SecurityContext:
    # 优先使用 DRF 已认证用户；手动解析 Bearer Token 仅作为兼容路径。
    if getattr(request, "user", None) and request.user.is_authenticated:
        profile = get_or_create_profile(request.user)
        return SecurityContext(request.user.username, profile.role, profile.workspace_key, True)

    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        context = context_from_token(token)
        if context.authenticated:
            return context

    # X-Role 只在关闭强制安全的开发环境生效，生产环境不能靠请求头提权。
    workspace_key = normalize_workspace_key(request.META.get("HTTP_X_WORKSPACE", DEFAULT_WORKSPACE_KEY))
    role = request.META.get("HTTP_X_ROLE", "").strip().lower()
    if role in {"admin", "operator", "visitor"} and not security_enforced():
        return SecurityContext(f"dev-{role}", role, workspace_key, True)

    return SecurityContext("anonymous", "visitor", workspace_key, False)


def context_from_token(token: str) -> SecurityContext:
    try:
        payload = AccessToken(token)
        user = get_user_model().objects.get(pk=payload["user_id"], is_active=True)
    except (TokenError, KeyError, get_user_model().DoesNotExist):
        return SecurityContext("anonymous", "visitor", DEFAULT_WORKSPACE_KEY, False)
    profile = get_or_create_profile(user)
    return SecurityContext(user.username, profile.role, normalize_workspace_key(profile.workspace_key), True)


def get_or_create_profile(user):
    from apps.agent_api.models import UserProfile

    role = UserProfile.Role.ADMIN if user.is_superuser else UserProfile.Role.VISITOR
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={"role": role, "workspace_key": DEFAULT_WORKSPACE_KEY},
    )
    return profile


def normalize_workspace_key(value: str | None) -> str:
    value = str(value or DEFAULT_WORKSPACE_KEY).strip().lower()
    cleaned = re.sub(r"[^a-z0-9_\-]", "-", value)
    return cleaned[:80] or DEFAULT_WORKSPACE_KEY


def security_enforced() -> bool:
    return bool(getattr(settings, "AGENT_SECURITY_ENFORCED", False))


def role_allowed(role: str, allowed_roles: Iterable[str]) -> bool:
    hierarchy = {"visitor": 0, "operator": 1, "admin": 2}
    required = max(hierarchy.get(item, 0) for item in allowed_roles)
    return hierarchy.get(role, 0) >= required


def detect_sensitive_input(text: str) -> str:
    lowered = text.lower()
    for pattern in SENSITIVE_INPUT_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return pattern
    return ""


def redact_sensitive_output(text: str) -> tuple[str, bool]:
    redacted = text
    for pattern in SECRET_OUTPUT_PATTERNS:
        redacted = re.sub(pattern, "[REDACTED_SECRET]", redacted)
    return redacted, redacted != text
