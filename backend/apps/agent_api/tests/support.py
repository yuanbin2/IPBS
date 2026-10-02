"""测试共享常量。"""

import tempfile
from itertools import count
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase

from ..models import UserProfile

NO_MODEL_ENV = {
    "RAG_EMBEDDING_MODE": "local_hash",
    "OPENAI_API_KEY": "",
    "OPENAI_EMBEDDING_API_KEY": "",
    "BAILIAN_API_KEY": "",
    "DASHSCOPE_API_KEY": "",
    "LANGSMITH_TRACING": "false",
    "LANGCHAIN_TRACING_V2": "false",
}

TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "knowledge_agent_test_media"

_IDENTITY_SEQUENCE = count(1)


class SecurityTransportTestCase(TestCase):
    """Run API requests through the same trusted HTTPS proxy contract as Railway."""

    def setUp(self):
        super().setUp()
        self.client.defaults["HTTP_X_FORWARDED_PROTO"] = "https"


class AuthenticatedApiTestCase(SecurityTransportTestCase):
    """Provide real JWT identities for permission-protected API integration tests."""

    default_role = UserProfile.Role.VISITOR

    def setUp(self):
        super().setUp()
        self.test_user, self.test_token = self.authenticate_test_user(self.default_role)

    def authenticate_test_user(self, role, workspace_key="default", username=None):
        sequence = next(_IDENTITY_SEQUENCE)
        username = username or f"security-{role}-{sequence}"
        password = "test-only-password-2026"
        user = get_user_model().objects.create_user(username=username, password=password)
        UserProfile.objects.create(user=user, role=role, workspace_key=workspace_key)
        response = self.client.post(
            "/api/agent/auth/login/",
            {"username": username, "password": password},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        if response.status_code != 200:
            raise AssertionError(f"Test identity login failed: {response.status_code} {response.content!r}")
        token = response.json()["token"]
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return user, token


class VisitorApiTestCase(AuthenticatedApiTestCase):
    default_role = UserProfile.Role.VISITOR


class OperatorApiTestCase(AuthenticatedApiTestCase):
    default_role = UserProfile.Role.OPERATOR


class AdminApiTestCase(AuthenticatedApiTestCase):
    default_role = UserProfile.Role.ADMIN


def post_and_run_commit_callbacks(test_case, path, data=None, **kwargs):
    """Run eager task callbacks explicitly; production dispatch still waits for commit."""
    with test_case.captureOnCommitCallbacks(execute=True):
        return test_case.client.post(path, data, **kwargs)
