"""统一错误格式（detail + code）测试。"""

from django.test import TestCase


class ApiErrorFormatTests(TestCase):
    """统一错误格式：detail 给人看，code 给前端做分支（coding-conventions.md §4.4）。"""

    def test_missing_field_error_carries_code(self):
        response = self.client.post(
            "/api/agent/chat/",
            {},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["code"], "missing_field")
        self.assertIn("detail", payload)

    def test_not_found_goes_through_exception_handler(self):
        response = self.client.get(
            "/api/agent/conversations/999999/",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "not_found")

    def test_validation_error_carries_code(self):
        response = self.client.post(
            "/api/agent/knowledge-bases/",
            {"description": "缺少名称"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "missing_field")
