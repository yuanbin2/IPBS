from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from ..views.auth import (
    AuthLoginView,
    AuthMeView,
    AuthRegisterView,
    SecurityAuditListView,
    SecurityStatusView,
)

urlpatterns = [
    path("auth/login/", AuthLoginView.as_view(), name="auth-login"),
    path("auth/register/", AuthRegisterView.as_view(), name="auth-register"),
    path("auth/me/", AuthMeView.as_view(), name="auth-me"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("security/status/", SecurityStatusView.as_view(), name="security-status"),
    path("security/audit-events/", SecurityAuditListView.as_view(), name="security-audit-events"),
]
