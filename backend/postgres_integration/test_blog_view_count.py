"""Verify public article view counts against real concurrent PostgreSQL requests."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

from django.db import close_old_connections, connection
from django.test import Client, TransactionTestCase

from apps.agent_api.models import BlogArticle


class BlogViewCountPostgresIntegrationTests(TransactionTestCase):
    def test_one_hundred_concurrent_public_detail_requests_are_counted(self):
        if connection.vendor != "postgresql":
            raise AssertionError("view-count concurrency acceptance requires PostgreSQL")

        article = BlogArticle.objects.create(
            title="Concurrent views",
            slug="concurrent-views",
            content="published article",
            status=BlogArticle.Status.PUBLISHED,
        )
        start = Event()

        def fetch_detail(_request_number):
            start.wait(timeout=10)
            close_old_connections()
            try:
                client = Client()
                response = client.get(
                    f"/api/agent/blog/articles/{article.slug}/",
                    secure=True,
                    HTTP_HOST="localhost",
                )
                return response.status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = [executor.submit(fetch_detail, index) for index in range(100)]
            start.set()
            statuses = [future.result(timeout=30) for future in futures]

        self.assertEqual(statuses, [200] * 100)
        article.refresh_from_db(fields=["view_count"])
        self.assertEqual(article.view_count, 100)
