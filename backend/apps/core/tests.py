from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings


class HealthCheckTests(SimpleTestCase):
    def setUp(self):
        self.client.defaults["HTTP_X_FORWARDED_PROTO"] = "https"

    def test_health_check_returns_platform_status(self):
        response = self.client.get("/api/health/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertIn("rag", response.json()["modules"])

    def test_missing_frontend_build_returns_actionable_response(self):
        with TemporaryDirectory() as directory:
            with override_settings(FRONTEND_DIST=Path(directory)):
                response = self.client.get("/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 503)
        self.assertIn("Frontend build not found", response.json()["detail"])


class ReadyCheckTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_X_FORWARDED_PROTO"] = "https"

    def test_ready_with_current_database_and_schema(self):
        response = self.client.get("/api/ready/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})

    def test_pending_migration_blocks_readiness_but_not_liveness(self):
        with patch("apps.core.views.MigrationExecutor") as executor:
            executor.return_value.migration_plan.return_value = [object()]
            response = self.client.get("/api/ready/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["reason"], "pending_migrations")
        self.assertEqual(self.client.get("/api/health/", HTTP_HOST="localhost").status_code, 200)

    def test_database_failure_blocks_readiness(self):
        with patch("apps.core.views.connections") as connections:
            connections.__getitem__.side_effect = OSError("isolated database failure")
            response = self.client.get("/api/ready/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["reason"], "database_or_schema")
