from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from ..views.auth import (
    AuthCookieLoginView,
    AuthCookieLogoutView,
    AuthCookieRefreshView,
    AuthCookieRegisterView,
    AuthCookieUpgradeView,
    AuthCsrfView,
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
    path("auth/csrf/", AuthCsrfView.as_view(), name="auth-csrf"),
    path("auth/cookie/login/", AuthCookieLoginView.as_view(), name="auth-cookie-login"),
    path("auth/cookie/register/", AuthCookieRegisterView.as_view(), name="auth-cookie-register"),
    path("auth/cookie/refresh/", AuthCookieRefreshView.as_view(), name="auth-cookie-refresh"),
    path("auth/cookie/upgrade/", AuthCookieUpgradeView.as_view(), name="auth-cookie-upgrade"),
    path("auth/cookie/logout/", AuthCookieLogoutView.as_view(), name="auth-cookie-logout"),
    path("security/status/", SecurityStatusView.as_view(), name="security-status"),
    path("security/audit-events/", SecurityAuditListView.as_view(), name="security-audit-events"),
]
