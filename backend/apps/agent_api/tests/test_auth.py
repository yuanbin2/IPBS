"""登录、注册、JWT 与工作区隔离测试。"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from ..models import SecurityAuditEvent, UserProfile
from .support import NO_MODEL_ENV


class AuthSecurityTests(TestCase):

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

    def test_user_can_register_and_receive_token(self):
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
        self.assertEqual(payload["user"]["role"], UserProfile.Role.ADMIN)
        self.assertEqual(payload["user"]["workspace_key"], "team-a")

    @override_settings(AGENT_SECURITY_ENFORCED=True)
    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_users_in_same_workspace_cannot_read_or_continue_each_others_conversations(self):
        User = get_user_model()
        user_a = User.objects.create_user(username="chat-user-a", password="pass12345")
        user_b = User.objects.create_user(username="chat-user-b", password="pass12345")
        UserProfile.objects.create(user=user_a, role=UserProfile.Role.VISITOR, workspace_key="shared")
        UserProfile.objects.create(user=user_b, role=UserProfile.Role.VISITOR, workspace_key="shared")

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
