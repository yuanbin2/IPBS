"""网页搜索工具的结果、失败与降级测试。"""

import json
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from django.conf import settings
from django.test import TestCase

from ..models import MCPTool


class WebSearchTests(TestCase):

    @patch("agent.mcp_tools.urlopen")
    def test_web_search_returns_external_results(self, mocked_urlopen):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps(
                    {
                        "RelatedTopics": [
                            {
                                "Text": "Django official documentation",
                                "FirstURL": "https://www.djangoproject.com/",
                            }
                        ]
                    }
                ).encode("utf-8")

        mocked_urlopen.return_value = FakeResponse()
        tool, _ = MCPTool.objects.update_or_create(
            name="web_search",
            defaults={
                "display_name": "网页搜索",
                "category": MCPTool.Category.WEB,
                "permission_scope": "network:web_search",
                "is_enabled": True,
            },
        )

        response = self.client.post(
            f"/api/agent/mcp-tools/{tool.id}/execute/",
            {"query": "Django"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Django official documentation", response.json()["output"])
        self.assertIn("provider=duckduckgo", response.json()["output"])

    @patch("agent.mcp_tools.urlopen", side_effect=URLError("network blocked"))
    def test_web_search_reports_network_failure_instead_of_empty_results(self, _mocked_urlopen):
        tool, _ = MCPTool.objects.update_or_create(
            name="web_search",
            defaults={
                "display_name": "网页搜索",
                "category": MCPTool.Category.WEB,
                "permission_scope": "network:web_search",
                "is_enabled": True,
            },
        )

        response = self.client.post(
            f"/api/agent/mcp-tools/{tool.id}/execute/",
            {"query": "Django"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("网页搜索失败", response.json()["output"])
        self.assertIn("network blocked", response.json()["output"])

    @patch("agent.mcp_tools.urlopen")
    def test_web_search_falls_back_to_bing_when_duckduckgo_fails(self, mocked_urlopen):
        class FakeResponse:
            def __init__(self, body: str):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return self.body.encode("utf-8")

        mocked_urlopen.side_effect = [
            URLError("duckduckgo blocked"),
            URLError("duckduckgo api blocked"),
            FakeResponse(
                '<html><body><li class="b_algo"><h2>'
                '<a href="https://docs.djangoproject.com/">Django documentation</a>'
                "</h2><p>Official Django docs.</p></li></body></html>"
            ),
        ]
        tool, _ = MCPTool.objects.update_or_create(
            name="web_search",
            defaults={
                "display_name": "网页搜索",
                "category": MCPTool.Category.WEB,
                "permission_scope": "network:web_search",
                "is_enabled": True,
            },
        )

        response = self.client.post(
            f"/api/agent/mcp-tools/{tool.id}/execute/",
            {"query": "Django official documentation"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("provider=bing", response.json()["output"])
        self.assertIn("Django documentation", response.json()["output"])

    def test_web_search_rewrites_query_reranks_official_result_and_blocks_private_url(self):
        from agent.mcp_tools import LocalMCPToolRunner

        runner = LocalMCPToolRunner(Path(settings.BASE_DIR).parent)
        queries = runner._build_search_queries("请帮我网页搜索 Django 官方文档有哪些")
        ranked = runner._deduplicate_and_rerank(
            "Django 官方文档",
            [
                ("Django tutorial from a blog", "https://example.com/django"),
                ("Django documentation", "https://docs.djangoproject.com/"),
                ("duplicate", "https://docs.djangoproject.com/"),
            ],
            limit=8,
        )

        self.assertEqual(queries[0], "Django 官方文档")
        self.assertEqual(
            runner._build_search_queries("please web search Django REST Framework official documentation")[0],
            "Django REST Framework official documentation",
        )
        self.assertEqual(ranked[0][1], "https://docs.djangoproject.com/")
        self.assertEqual(len(ranked), 2)
        self.assertEqual(runner._normalize_duckduckgo_url("https://127.0.0.1/admin"), "")
