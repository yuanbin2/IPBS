"""登录、注册、JWT 与工作区隔离测试。"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from ..models import SecurityAuditEvent, UserProfile
from .support import NO_MODEL_ENV


class AuthSecurityTests(TestCase):

    def setUp(self):
        # Railway terminates TLS at the edge and forwards this trusted header.
        self.client.defaults["HTTP_X_FORWARDED_PROTO"] = "https"

    def test_cookie_session_requires_csrf_rotates_and_revokes_refresh(self):
        user = get_user_model().objects.create_user(username="cookie-user", password="pass12345")
        UserProfile.objects.create(user=user, role=UserProfile.Role.VISITOR, workspace_key="default")
        browser = Client(
            enforce_csrf_checks=True,
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_HOST="localhost",
            HTTP_ORIGIN="https://localhost",
        )
        csrf = browser.get("/api/agent/auth/csrf/")
        self.assertEqual(csrf.status_code, 200)
        csrf_token = csrf.json()["csrfToken"]

        no_csrf = browser.post(
            "/api/agent/auth/cookie/login/",
            {"username": "cookie-user", "password": "pass12345"},
            content_type="application/json",
        )
        self.assertEqual(no_csrf.status_code, 403)
        login = browser.post(
            "/api/agent/auth/cookie/login/",
            {"username": "cookie-user", "password": "pass12345"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(login.status_code, 200)
        self.assertNotIn("refresh", login.json())
        self.assertIn("access", login.json())
        refresh_cookie = login.cookies["blog_refresh"]
        self.assertTrue(refresh_cookie["httponly"])
        self.assertEqual(refresh_cookie["samesite"], "Lax")
        old_refresh = refresh_cookie.value

        evil_origin = browser.post(
            "/api/agent/auth/cookie/refresh/",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_ORIGIN="https://attacker.example",
        )
        self.assertEqual(evil_origin.status_code, 403)

        self.assertEqual(browser.post("/api/agent/auth/cookie/refresh/").status_code, 403)
        refreshed = browser.post("/api/agent/auth/cookie/refresh/", HTTP_X_CSRFTOKEN=csrf_token)
        self.assertEqual(refreshed.status_code, 200)
        self.assertNotIn("refresh", refreshed.json())
        current_refresh = refreshed.cookies["blog_refresh"].value
        self.assertNotEqual(current_refresh, old_refresh)

        browser.cookies["blog_refresh"] = old_refresh
        replay = browser.post("/api/agent/auth/cookie/refresh/", HTTP_X_CSRFTOKEN=csrf_token)
        self.assertEqual(replay.status_code, 401)

        browser.cookies["blog_refresh"] = current_refresh
        logout = browser.post("/api/agent/auth/cookie/logout/", HTTP_X_CSRFTOKEN=csrf_token)
        self.assertEqual(logout.status_code, 204)
        browser.cookies["blog_refresh"] = current_refresh
        self.assertEqual(browser.post("/api/agent/auth/cookie/refresh/", HTTP_X_CSRFTOKEN=csrf_token).status_code, 401)

    def test_cookie_registration_never_returns_refresh_in_json(self):
        browser = Client(
            enforce_csrf_checks=True,
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_HOST="localhost",
            HTTP_ORIGIN="https://localhost",
        )
        csrf_token = browser.get("/api/agent/auth/csrf/").json()["csrfToken"]
        response = browser.post(
            "/api/agent/auth/cookie/register/",
            {"username": "cookie-register", "password": "pass12345"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("refresh", response.json())
        self.assertIn("blog_refresh", response.cookies)

    @override_settings(CSRF_COOKIE_SECURE=True)
    def test_cookie_refresh_is_secure_under_production_cookie_settings(self):
        user = get_user_model().objects.create_user(username="secure-cookie", password="pass12345")
        UserProfile.objects.create(user=user, role=UserProfile.Role.VISITOR, workspace_key="default")
        browser = Client(
            enforce_csrf_checks=True,
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_HOST="localhost",
            HTTP_ORIGIN="https://localhost",
        )
        csrf_token = browser.get("/api/agent/auth/csrf/").json()["csrfToken"]
        response = browser.post(
            "/api/agent/auth/cookie/login/",
            {"username": "secure-cookie", "password": "pass12345"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies["blog_refresh"]["secure"])

    def test_legacy_refresh_rotation_rejects_old_body_token(self):
        user = get_user_model().objects.create_user(username="legacy", password="pass12345")
        UserProfile.objects.create(user=user, role=UserProfile.Role.VISITOR, workspace_key="default")
        login = self.client.post(
            "/api/agent/auth/login/",
            {"username": "legacy", "password": "pass12345"},
            content_type="application/json",
        )
        old_refresh = login.json()["refresh"]
        first = self.client.post("/api/agent/auth/refresh/", {"refresh": old_refresh}, content_type="application/json")
        replay = self.client.post("/api/agent/auth/refresh/", {"refresh": old_refresh}, content_type="application/json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 401)

    def test_legacy_browser_refresh_upgrades_once_to_cookie(self):
        user = get_user_model().objects.create_user(username="upgrade-user", password="pass12345")
        UserProfile.objects.create(user=user, role=UserProfile.Role.VISITOR, workspace_key="default")
        login = self.client.post(
            "/api/agent/auth/login/",
            {"username": "upgrade-user", "password": "pass12345"},
            content_type="application/json",
        )
        legacy_refresh = login.json()["refresh"]
        browser = Client(
            enforce_csrf_checks=True,
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_HOST="localhost",
            HTTP_ORIGIN="https://localhost",
        )
        csrf_token = browser.get("/api/agent/auth/csrf/").json()["csrfToken"]
        upgrade = browser.post(
            "/api/agent/auth/cookie/upgrade/",
            {"refresh": legacy_refresh},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(upgrade.status_code, 200)
        self.assertNotIn("refresh", upgrade.json())
        self.assertTrue(upgrade.cookies["blog_refresh"]["httponly"])
        replay = browser.post(
            "/api/agent/auth/cookie/upgrade/",
            {"refresh": legacy_refresh},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(replay.status_code, 401)

    @override_settings(AGENT_SECURITY_ENFORCED=True)
    def test_legacy_django_session_cookie_cannot_authorize_agent_api(self):
        user = get_user_model().objects.create_user(
            username="old-session-admin", password="pass12345", is_superuser=True
        )
        UserProfile.objects.create(user=user, role=UserProfile.Role.ADMIN, workspace_key="default")
        self.client.force_login(user)
        without_jwt = self.client.get("/api/agent/security/status/")
        me = self.client.get("/api/agent/auth/me/")
        self.assertEqual(without_jwt.status_code, 403)
        self.assertFalse(me.json()["authenticated"])

        login = self.client.post(
            "/api/agent/auth/login/",
            {"username": "old-session-admin", "password": "pass12345"},
            content_type="application/json",
        )
        with_jwt = self.client.get(
            "/api/agent/security/status/",
            HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}",
        )
        self.assertEqual(with_jwt.status_code, 200)

    @override_settings(
        AGENT_SECURITY_ENFORCED=True,
        SECURE_SSL_REDIRECT=True,
        SECURE_HSTS_SECONDS=3600,
    )
    def test_railway_forwarded_https_does_not_redirect(self):
        response = self.client.get("/api/agent/security/status/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Strict-Transport-Security"], "max-age=3600")

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_unforwarded_http_request_redirects_to_https(self):
        self.client.defaults.pop("HTTP_X_FORWARDED_PROTO")

        response = self.client.get("/api/agent/security/status/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 301)
        self.assertTrue(response["Location"].startswith("https://localhost/"))

    @override_settings(AGENT_SECURITY_ENFORCED=True)
    def test_security_enforced_blocks_admin_endpoint_for_visitor(self):
        response = self.client.get("/api/agent/security/status/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(SecurityAuditEvent.objects.first().event_type, SecurityAuditEvent.EventType.ACCESS_DENIED)

    @override_settings(AGENT_SECURITY_ENFORCED=True)
    def test_admin_can_login_and_access_security_status(self):
        user = get_user_model().objects.create_user(username="admin", password="pass12345", is_superuser=True)
        UserProfile.objects.create(user=user, role=UserProfile.Role.ADMIN, workspace_key="default")

        login_response = self.client.post(
            "/api/agent/auth/login/",
            {"username": "admin", "password": "pass12345"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        token = login_response.json()["token"]
        response = self.client.get(
            "/api/agent/security/status/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_HOST="localhost",
        )

        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["context"]["role"], UserProfile.Role.ADMIN)
        self.assertTrue(
            SecurityAuditEvent.objects.filter(event_type=SecurityAuditEvent.EventType.LOGIN, actor="admin").exists()
        )

    @override_settings(AGENT_SECURITY_ENFORCED=True)
    def test_public_registration_cannot_grant_privileged_role_or_workspace(self):
        response = self.client.post(
            "/api/agent/auth/register/",
            {
                "username": "new-admin",
                "password": "pass12345",
                "role": "admin",
                "workspace_key": "team-a",
            },
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertIn("token", payload)
        self.assertEqual(payload["user"]["role"], UserProfile.Role.VISITOR)
        self.assertEqual(payload["user"]["workspace_key"], "default")
        user = get_user_model().objects.get(username="new-admin")
        self.assertFalse(user.is_staff)
        privileged_response = self.client.get(
            "/api/agent/security/status/",
            HTTP_AUTHORIZATION=f"Bearer {payload['token']}",
            HTTP_HOST="localhost",
        )
        self.assertEqual(privileged_response.status_code, 403)

    @override_settings(AGENT_SECURITY_ENFORCED=True)
    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_users_in_same_workspace_cannot_read_or_continue_each_others_conversations(self):
        User = get_user_model()
        user_a = User.objects.create_user(username="chat-user-a", password="pass12345")
        user_b = User.objects.create_user(username="chat-user-b", password="pass12345")
        UserProfile.objects.create(user=user_a, role=UserProfile.Role.OPERATOR, workspace_key="shared")
        UserProfile.objects.create(user=user_b, role=UserProfile.Role.OPERATOR, workspace_key="shared")

        login_a = self.client.post(
            "/api/agent/auth/login/",
            {"username": "chat-user-a", "password": "pass12345"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        token_a = login_a.json()["token"]
        chat = self.client.post(
            "/api/agent/chat/",
            {"message": "private question"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token_a}",
            HTTP_HOST="localhost",
        )
        conversation_id = chat.json()["conversation"]["id"]

        login_b = self.client.post(
            "/api/agent/auth/login/",
            {"username": "chat-user-b", "password": "pass12345"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        token_b = login_b.json()["token"]
        list_response = self.client.get(
            "/api/agent/conversations/",
            HTTP_AUTHORIZATION=f"Bearer {token_b}",
            HTTP_HOST="localhost",
        )
        detail_response = self.client.get(
            f"/api/agent/conversations/{conversation_id}/",
            HTTP_AUTHORIZATION=f"Bearer {token_b}",
            HTTP_HOST="localhost",
        )
        continue_response = self.client.post(
            "/api/agent/chat/",
            {"message": "try to continue", "conversation_id": conversation_id},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token_b}",
            HTTP_HOST="localhost",
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json(), [])
        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(continue_response.status_code, 404)
