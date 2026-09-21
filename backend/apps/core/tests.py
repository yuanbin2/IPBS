from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase, override_settings


class HealthCheckTests(SimpleTestCase):
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
