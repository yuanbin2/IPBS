from django.test import SimpleTestCase


class HealthCheckTests(SimpleTestCase):
    def test_health_check_returns_platform_status(self):
        response = self.client.get("/api/health/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertIn("rag", response.json()["modules"])

