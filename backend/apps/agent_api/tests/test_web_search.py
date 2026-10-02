"""网页搜索工具的结果、失败与降级测试。"""

import json
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from django.conf import settings

from ..models import MCPTool
from .support import NO_MODEL_ENV, OperatorApiTestCase


class WebSearchTests(OperatorApiTestCase):

    @patch("agent.web_search.urlopen")
    @patch.dict("os.environ", {**NO_MODEL_ENV, "WEB_SEARCH_PROVIDER": "duckduckgo"})
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

    @patch("agent.web_search.urlopen", side_effect=URLError("network blocked"))
    @patch.dict("os.environ", {**NO_MODEL_ENV, "WEB_SEARCH_PROVIDER": "duckduckgo"})
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

    @patch("agent.web_search.urlopen")
    @patch.dict("os.environ", {**NO_MODEL_ENV, "WEB_SEARCH_PROVIDER": "duckduckgo"})
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


class InternetAgentTests(OperatorApiTestCase):
    """联网 Agent：显式开关、追问重写与降级路径。"""

    @patch("agent.mcp_tools.LocalMCPToolRunner.run")
    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_web_result_secrets_are_redacted_in_rest_and_sse(self, mocked_run):
        from agent.mcp_tools import MCPToolExecution

        MCPTool.objects.update_or_create(
            name="web_search",
            defaults={
                "display_name": "网页搜索",
                "category": MCPTool.Category.WEB,
                "permission_scope": "network:web_search",
                "is_enabled": True,
                "requires_approval": False,
            },
        )
        secret = "sk-abcdefghijklmnop"
        mocked_run.return_value = MCPToolExecution("web_search", "public query", f"[1] public result {secret}")
        for path in ("/api/agent/chat/", "/api/agent/chat/stream/"):
            response = self.client.post(
                path,
                {"message": "网页搜索公开资料"},
                content_type="application/json",
                HTTP_HOST="localhost",
            )
            self.assertEqual(response.status_code, 200)
            body = (
                b"".join(response.streaming_content).decode("utf-8")
                if response.streaming
                else response.content.decode("utf-8")
            )
            self.assertNotIn(secret, body)
            self.assertIn("[REDACTED_SECRET]", body)
            self.assertIn("security_filter -> output redacted", body)

    @patch("agent.mcp_tools.LocalMCPToolRunner.run")
    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_internet_toggle_searches_web_and_then_uses_answer_path(self, mocked_run):
        from agent.mcp_tools import MCPToolExecution

        MCPTool.objects.update_or_create(
            name="web_search",
            defaults={
                "display_name": "网页搜索",
                "category": MCPTool.Category.WEB,
                "permission_scope": "network:web_search",
                "is_enabled": True,
                "requires_approval": False,
            },
        )
        mocked_run.return_value = MCPToolExecution("web_search", "Python 3.14", "[1] Python release notes")
        response = self.client.post(
            "/api/agent/chat/",
            {"message": "Python 3.14 有什么变化？", "internet_enabled": True},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["route"], "internet")
        self.assertEqual(payload["tool_calls"][0]["name"], "mcp:web_search")
        self.assertIn("网页搜索结果", payload["answer"])

    @patch("agent.mcp_tools.LocalMCPToolRunner.run")
    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_explicit_web_search_runs_even_when_internet_toggle_is_off(self, mocked_run):
        from agent.mcp_tools import MCPToolExecution

        MCPTool.objects.update_or_create(
            name="web_search",
            defaults={
                "display_name": "网页搜索",
                "category": MCPTool.Category.WEB,
                "permission_scope": "network:web_search",
                "is_enabled": True,
                "requires_approval": False,
            },
        )
        mocked_run.return_value = MCPToolExecution("web_search", "Python 官方文档", "[1] Python docs")
        response = self.client.post(
            "/api/agent/chat/",
            {"message": "网页搜索 Python 官方文档", "internet_enabled": False},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tool_calls"][0]["name"], "mcp:web_search")
        mocked_run.assert_called_once()

    @patch("agent.mcp_tools.LocalMCPToolRunner.run")
    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_internet_follow_up_rewrites_search_query_with_conversation_context(self, mocked_run):
        from agent.mcp_tools import MCPToolExecution

        MCPTool.objects.update_or_create(
            name="web_search",
            defaults={
                "display_name": "网页搜索",
                "category": MCPTool.Category.WEB,
                "permission_scope": "network:web_search",
                "is_enabled": True,
                "requires_approval": False,
            },
        )
        mocked_run.return_value = MCPToolExecution("web_search", "query", "[1] result")
        first = self.client.post(
            "/api/agent/chat/",
            {"message": "介绍一下 Python 3.14"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        conversation_id = first.json()["conversation"]["id"]

        second = self.client.post(
            "/api/agent/chat/",
            {
                "message": "那它有哪些重要的新特性？",
                "conversation_id": conversation_id,
                "internet_enabled": True,
            },
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(second.status_code, 200)
        rewritten_query = mocked_run.call_args.args[1]
        self.assertIn("Python 3.14", rewritten_query)
        self.assertIn("重要的新特性", rewritten_query)
        self.assertEqual(second.json()["tool_calls"][0]["input"], rewritten_query)
        self.assertTrue(any("internet_query_rewrite" in item for item in second.json()["trace"]))
