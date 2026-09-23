"""聊天执行与 Supervisor 路由：工具短路、检索优先、追问消解与路由断言。"""

from unittest.mock import patch

from django.test import TestCase

from agent.multi_agent import MultiAgentSupervisor

from ..models import AgentObservation, AgentRun, BlogArticle, Conversation, Message
from ..services.rag import expand_multilingual_query, keyword_similarity
from .support import NO_MODEL_ENV


class ChatExecutionTests(TestCase):

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_agent_chat_uses_calculator_tool_and_persists_history(self):
        response = self.client.post(
            "/api/agent/chat/",
            {"message": "帮我计算 12 * 8"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("96", payload["answer"])
        self.assertEqual(payload["tool_calls"][0]["name"], "calculator")
        self.assertIn("sources", payload)
        self.assertIn("total_tokens", payload["token_usage"])
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(Message.objects.count(), 2)
        self.assertEqual(AgentRun.objects.count(), 1)
        self.assertEqual(AgentObservation.objects.count(), 1)
        self.assertGreaterEqual(AgentObservation.objects.first().latency_ms, 0)

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_agent_chat_searches_before_joke_generation(self):
        response = self.client.post(
            "/api/agent/chat/",
            {"message": "说一个笑话"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["route"], "retrieve")
        self.assertEqual(payload["tool_calls"][0]["name"], "knowledge_search")
        self.assertEqual(payload["sources"], [])
        self.assertNotIn("数据库中没有", payload["answer"])

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_supervisor_routes_blog_question_to_blog_agent(self):
        response = self.client.post(
            "/api/agent/chat/",
            {"message": "这个博客项目的技术栈是什么？"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["supervisor"]["selected_agent"], "blog_agent")
        self.assertIn("supervisor -> blog_agent", payload["trace"][1])
        self.assertGreaterEqual(len(payload["tool_calls"]), 1)

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_uploaded_resume_request_routes_to_private_workspace_rag(self):
        response = self.client.post(
            "/api/agent/chat/",
            {"message": "看一下卫晓斌的简历"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["supervisor"]["selected_agent"], "rag_agent")
        self.assertIn("uploaded private workspace document", payload["supervisor"]["reason"])

    def test_chinese_person_affiliation_query_adds_english_name_aliases(self):
        expanded = expand_multilingual_query("苏轩是哪个学校")

        self.assertIn("Xuan Su", expanded)
        self.assertIn("Su Xuan", expanded)
        self.assertIn("university affiliation institution", expanded)

    def test_three_character_chinese_name_and_resume_title_match(self):
        expanded = expand_multilingual_query("卫晓斌相关信息")

        self.assertIn("Xiaobin Wei", expanded)
        self.assertIn("Wei Xiaobin", expanded)
        self.assertGreaterEqual(
            keyword_similarity("卫晓斌相关信息", "卫晓斌简历", "Python developer"),
            0.8,
        )

    def test_chinese_scattering_imaging_query_adds_english_technical_aliases(self):
        expanded = expand_multilingual_query("散射成像")

        self.assertIn("scattering imaging", expanded)
        self.assertIn("imaging through scattering media", expanded)

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_unseen_short_technical_topic_routes_to_query_expansion_rag(self):
        response = self.client.post(
            "/api/agent/chat/",
            {"message": "医学成像"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["supervisor"]["selected_agent"], "rag_agent")
        self.assertIn("agent-generated multilingual retrieval", payload["supervisor"]["reason"])

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_system_stack_question_returns_grounded_complete_stack_without_generic_technologies(self):
        response = self.client.post(
            "/api/agent/chat/",
            {"message": "本博客系统所使用的技术栈", "internet_enabled": False},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["supervisor"]["selected_agent"], "blog_agent")
        self.assertIn("system technology-stack facts", payload["supervisor"]["reason"])
        for technology in [
            "Vue 3",
            "TypeScript",
            "Django REST Framework",
            "PostgreSQL",
            "Redis",
            "RabbitMQ",
            "Celery",
            "LangGraph",
            "MCP",
            "Docker Compose",
            "Nginx",
            "GitHub Actions",
        ]:
            self.assertIn(technology, payload["answer"])
        for unsupported in ["Java", "Spring", "Angular", "AWS", "Azure"]:
            self.assertNotIn(unsupported, payload["answer"])
        self.assertEqual(payload["sources"][0]["document_title"], "本博客系统完整技术栈与架构")

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_follow_up_uses_previous_messages_from_same_conversation(self):
        first = self.client.post(
            "/api/agent/chat/",
            {"message": "本博客系统所使用的技术栈"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        conversation_id = first.json()["conversation"]["id"]

        second = self.client.post(
            "/api/agent/chat/",
            {"message": "那后端呢？", "conversation_id": conversation_id},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(second.status_code, 200)
        payload = second.json()
        self.assertEqual(payload["supervisor"]["selected_agent"], "blog_agent")
        self.assertIn("context_memory -> 2 previous messages", payload["trace"])
        self.assertEqual(Message.objects.filter(conversation_id=conversation_id).count(), 4)

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_rag_follow_up_rewrites_pronoun_with_previous_person_context(self):
        first = self.client.post(
            "/api/agent/chat/",
            {"message": "检索卫晓斌的信息"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        conversation_id = first.json()["conversation"]["id"]

        second = self.client.post(
            "/api/agent/chat/",
            {"message": "他是哪个学校的？", "conversation_id": conversation_id},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(second.status_code, 200)
        payload = second.json()
        self.assertEqual(payload["supervisor"]["selected_agent"], "rag_agent")
        self.assertTrue(
            any(
                item.startswith("context_query_rewrite ->") and "卫晓斌" in item and "学校" in item
                for item in payload["trace"]
            )
        )
        knowledge_calls = [item for item in payload["tool_calls"] if item["name"] == "knowledge_search"]
        self.assertTrue(knowledge_calls)
        self.assertIn("卫晓斌", knowledge_calls[0]["input"])

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_supervisor_routes_statistics_question_to_sql_analysis_agent(self):
        BlogArticle.objects.create(
            title="Stats Article",
            slug="stats-article",
            content="content",
            status=BlogArticle.Status.PUBLISHED,
        )

        response = self.client.post(
            "/api/agent/chat/",
            {"message": "统计一下当前有多少文章和文档"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["supervisor"]["selected_agent"], "sql_analysis_agent")
        self.assertEqual(payload["tool_calls"][0]["name"], "safe_sql_analytics")
        self.assertIn("published_articles", payload["tool_calls"][0]["output"])
        self.assertNotIn("CREATE TABLE", payload["answer"])

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_explicit_retrieval_uses_private_workspace_rag(self):
        response = self.client.post(
            "/api/agent/chat/",
            {"message": "检索博客中关于项目成功的内容", "internet_enabled": False},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["supervisor"]["selected_agent"], "rag_agent")
        self.assertEqual(payload["tool_calls"][0]["name"], "knowledge_search")

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_specialized_response_keeps_sql_supervisor_identity(self):
        response = self.client.post(
            "/api/agent/chat/",
            {"message": "统计文章数量"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["route"], "sql_analysis_agent")
        self.assertEqual(payload["supervisor"]["selected_agent"], "sql_analysis_agent")

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_general_question_retrieves_before_model_fallback(self):
        response = self.client.post(
            "/api/agent/chat/",
            {"message": "解释一下 Python 的 GIL", "internet_enabled": False},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["supervisor"]["selected_agent"], "rag_agent")
        self.assertEqual(payload["sources"], [])
        self.assertEqual(payload["tool_calls"][0]["name"], "knowledge_search")
        self.assertIn("retrieval_fallback -> no relevant source; direct generation", payload["trace"])

    def test_agent_chat_requires_message(self):
        response = self.client.post(
            "/api/agent/chat/",
            {},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 400)


class SupervisorRoutingTests(TestCase):
    """Supervisor 路由纯函数单测（蓝图 DAG/T5）：不依赖数据库和 LLM。"""

    def test_is_mcp_request_detects_explicit_mcp_keyword(self):
        self.assertTrue(MultiAgentSupervisor.is_mcp_request("用 MCP 工具查一下"))

    def test_is_mcp_request_detects_capability_keywords(self):
        for message in ["帮我网页搜索 LangGraph", "看看 git 仓库状态", "现在几点了"]:
            with self.subTest(message=message):
                self.assertTrue(MultiAgentSupervisor.is_mcp_request(message))

    def test_is_mcp_request_rejects_plain_chat(self):
        self.assertFalse(MultiAgentSupervisor.is_mcp_request("你好，帮我写一首诗"))

    def test_select_mcp_tool_name_matches_each_capability(self):
        cases = {
            "现在几点": "current_time",
            "git 仓库信息": "git_repo_info",
            "帮我网页搜索": "web_search",
            "数据库统计": "safe_database_stats",
            "搜索本地文件": "local_file_search",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(MultiAgentSupervisor.select_mcp_tool_name(message), expected)

    def test_select_mcp_tool_name_covers_merged_web_search_phrases(self):
        # C2 合并根 agent/ 时补充的触发词，防止回归
        for message in ["在网上搜索一下这个报错", "用网络查找相关资料"]:
            with self.subTest(message=message):
                self.assertEqual(MultiAgentSupervisor.select_mcp_tool_name(message), "web_search")

    def test_is_system_stack_question_detects_self_reference(self):
        self.assertTrue(MultiAgentSupervisor.is_system_stack_question("本系统用了什么技术栈"))
        self.assertFalse(MultiAgentSupervisor.is_system_stack_question("今天天气怎么样"))
