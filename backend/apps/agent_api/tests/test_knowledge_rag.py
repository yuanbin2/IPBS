"""混合检索质量：关键词信号、邻域扩展、pgvector 优先与全文摘要读取。"""

from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from agent.simple_agent import SimpleToolCallingAgent

from ..models import BlogArticle, Document, DocumentChunk, EmbeddingRecord, KnowledgeBase
from ..services.blog_agent import PublicBlogAgent
from ..services.embedding_space import embedding_space_identity
from ..services.rag import (
    SearchResult,
    expand_search_results_with_neighbors,
    local_embedding,
    query_entity_terms,
    search_knowledge_base,
)
from ..services.vector_store import VectorMatch
from .support import NO_MODEL_ENV, TEST_MEDIA_ROOT, OperatorApiTestCase, post_and_run_commit_callbacks


class KnowledgeRagTests(OperatorApiTestCase):

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_knowledge_search_returns_relevant_chunks(self):
        upload = SimpleUploadedFile(
            "knowledge.txt",
            (
                b"Agentic RAG means the agent retrieves context first.\n\n"
                b"The retrieved context is inserted into the prompt before the model answers."
            ),
            content_type="text/plain",
        )
        post_and_run_commit_callbacks(
            self,
            "/api/agent/documents/",
            {"file": upload, "title": "Agentic RAG"},
            HTTP_HOST="localhost",
        )

        response = self.client.post(
            "/api/agent/knowledge-search/",
            {"query": "retrieved context prompt", "limit": 3},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(len(payload), 1)
        self.assertEqual(payload[0]["document_title"], "Agentic RAG")

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_uploaded_sample_is_indexed_searchable_and_available_to_chat_rag(self):
        workspace = "sample-workspace"
        self.authenticate_test_user("operator", workspace_key=workspace)
        upload = SimpleUploadedFile(
            "codex-rag-smoke.txt",
            (b"Codex RAG smoke marker ALPHA42.\n\n" b"The uploaded sample says the retrieval answer color is teal."),
            content_type="text/plain",
        )

        upload_response = post_and_run_commit_callbacks(
            self,
            "/api/agent/documents/",
            {"file": upload, "title": "Codex RAG Smoke Sample"},
            HTTP_HOST="localhost",
            HTTP_X_WORKSPACE=workspace,
        )

        self.assertEqual(upload_response.status_code, 202)
        upload_payload = upload_response.json()
        document = Document.objects.select_related("knowledge_base").get(pk=upload_payload["id"])
        self.assertEqual(document.status, Document.Status.READY)
        self.assertEqual(document.workspace_key, workspace)
        self.assertEqual(document.knowledge_base.workspace_key, workspace)
        self.assertGreaterEqual(document.chunk_count, 1)
        self.assertEqual(DocumentChunk.objects.filter(document=document).count(), document.chunk_count)
        self.assertEqual(EmbeddingRecord.objects.filter(chunk__document=document).count(), document.chunk_count)

        search_response = self.client.post(
            "/api/agent/knowledge-search/",
            {"query": "ALPHA42 retrieval answer color teal", "limit": 3},
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_X_WORKSPACE=workspace,
        )

        self.assertEqual(search_response.status_code, 200)
        search_payload = search_response.json()
        self.assertGreaterEqual(len(search_payload), 1)
        self.assertEqual(search_payload[0]["document_title"], "Codex RAG Smoke Sample")
        self.assertIn("teal", search_payload[0]["content"])

        chat_response = self.client.post(
            "/api/agent/chat/",
            {"message": "请根据知识库回答 ALPHA42 的 retrieval answer color 是什么？"},
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_X_WORKSPACE=workspace,
        )

        self.assertEqual(chat_response.status_code, 200)
        chat_payload = chat_response.json()
        self.assertEqual(chat_payload["supervisor"]["selected_agent"], "rag_agent")
        self.assertEqual(chat_payload["tool_calls"][0]["name"], "knowledge_search")
        self.assertGreaterEqual(len(chat_payload["sources"]), 1)
        self.assertEqual(chat_payload["sources"][0]["document_title"], "Codex RAG Smoke Sample")
        self.assertIn("teal", chat_payload["sources"][0]["content"])

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_uploaded_wei_xiaobin_resume_is_searchable_from_related_info_question(self):
        workspace = "resume-workspace"
        self.authenticate_test_user("operator", workspace_key=workspace)
        upload = SimpleUploadedFile(
            "wei-xiaobin-resume.txt",
            (
                "卫晓斌个人简历\n\n"
                "姓名：卫晓斌\n"
                "教育经历：重庆三峡科技大学 硕士 计算机技术 2024-2027；晋中学院 本科 计算机科学与技术 2020-2024。\n"
                "方向：Python 后端开发、Django、Vue、RAG 知识库和 Agent 工程。\n"
                "项目：构建个人博客智能体系统，支持文档上传、知识库检索和问答引用。"
            ).encode(),
            content_type="text/plain",
        )

        upload_response = post_and_run_commit_callbacks(
            self,
            "/api/agent/documents/",
            {"file": upload, "title": "卫晓斌-agent开发"},
            HTTP_HOST="localhost",
            HTTP_X_WORKSPACE=workspace,
        )
        self.assertEqual(upload_response.status_code, 202)
        document = Document.objects.get(pk=upload_response.json()["id"])
        self.assertEqual(document.status, Document.Status.READY)

        search_response = self.client.post(
            "/api/agent/knowledge-search/",
            {"query": "卫晓斌相关信息", "limit": 3},
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_X_WORKSPACE=workspace,
        )
        self.assertEqual(search_response.status_code, 200)
        search_payload = search_response.json()
        self.assertGreaterEqual(len(search_payload), 1)
        self.assertEqual(search_payload[0]["document_title"], "卫晓斌-agent开发")
        self.assertGreaterEqual(search_payload[0]["score"], SimpleToolCallingAgent.min_relevance_score)
        self.assertIn("Python 后端开发", search_payload[0]["content"])

        chat_response = self.client.post(
            "/api/agent/chat/",
            {"message": "卫晓斌是哪个学校的"},
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_X_WORKSPACE=workspace,
        )
        self.assertEqual(chat_response.status_code, 200)
        chat_payload = chat_response.json()
        self.assertEqual(chat_payload["supervisor"]["selected_agent"], "rag_agent")
        self.assertEqual(chat_payload["tool_calls"][0]["name"], "knowledge_search")
        self.assertGreaterEqual(len(chat_payload["sources"]), 1)
        self.assertEqual(chat_payload["sources"][0]["document_title"], "卫晓斌-agent开发")
        self.assertIn("卫晓斌", chat_payload["sources"][0]["content"])
        self.assertIn("硕士：重庆三峡科技大学", chat_payload["answer"])
        self.assertIn("本科：晋中学院", chat_payload["answer"])
        self.assertNotIn("我先根据本地知识库找到了这些", chat_payload["answer"])

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_knowledge_search_uses_keyword_signal_when_vectors_are_weak(self):
        knowledge_base = KnowledgeBase.objects.create(name="hybrid")
        document = Document.objects.create(
            knowledge_base=knowledge_base,
            title="LangGraph RAG Notes",
            status=Document.Status.READY,
        )
        weak_chunk = DocumentChunk.objects.create(
            document=document,
            knowledge_base=knowledge_base,
            chunk_index=0,
            content="This paragraph is about generic platform setup.",
        )
        strong_chunk = DocumentChunk.objects.create(
            document=document,
            knowledge_base=knowledge_base,
            chunk_index=1,
            content="Agentic RAG stores retrieved context inside the final prompt before answering.",
        )
        identity = embedding_space_identity(384, mode="local_hash")
        EmbeddingRecord.objects.create(
            chunk=weak_chunk,
            vector=local_embedding(weak_chunk.content),
            status=EmbeddingRecord.Status.READY,
            **identity.as_record_fields(),
        )
        EmbeddingRecord.objects.create(
            chunk=strong_chunk,
            vector=local_embedding(strong_chunk.content),
            status=EmbeddingRecord.Status.READY,
            **identity.as_record_fields(),
        )

        results = search_knowledge_base("retrieved context prompt", knowledge_base_id=knowledge_base.id, limit=2)

        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].chunk_id, strong_chunk.id)

    def test_retrieval_expands_hit_with_ordered_neighbor_chunks(self):
        knowledge_base = KnowledgeBase.objects.create(name="neighbor context")
        document = Document.objects.create(
            knowledge_base=knowledge_base,
            title="Sequential Guide",
            status=Document.Status.READY,
            chunk_count=5,
        )
        chunks = [
            DocumentChunk.objects.create(
                document=document,
                knowledge_base=knowledge_base,
                chunk_index=index,
                content=f"ordered section {index}",
            )
            for index in range(5)
        ]
        hit = SearchResult(
            document_id=document.id,
            document_title=document.title,
            chunk_id=chunks[2].id,
            chunk_index=2,
            content=chunks[2].content,
            score=0.9,
        )

        expanded = expand_search_results_with_neighbors(
            [hit],
            neighbor_window=1,
            max_results=3,
        )

        self.assertEqual([item.chunk_index for item in expanded], [1, 2, 3])
        self.assertEqual([item.document_id for item in expanded], [document.id] * 3)
        self.assertEqual(expanded[1].score, 0.9)

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_blog_agent_reads_all_ordered_chunks_for_full_article_request(self):
        knowledge_base = KnowledgeBase.objects.create(name="full article")
        document = Document.objects.create(
            knowledge_base=knowledge_base,
            title="博客：跨片段教程",
            status=Document.Status.READY,
            chunk_count=3,
        )
        for index, content in enumerate(["开篇背景", "中间实现", "末尾结论"]):
            DocumentChunk.objects.create(
                document=document,
                knowledge_base=knowledge_base,
                chunk_index=index,
                content=content,
            )
        BlogArticle.objects.create(
            title="跨片段教程",
            slug="cross-chunk-guide",
            summary="一篇覆盖完整流程的教程。",
            content="# 背景\n开篇。\n\n## 实现\n中间。\n\n## 最终结论\n末尾。",
            status=BlogArticle.Status.PUBLISHED,
            knowledge_document=document,
        )
        agent = PublicBlogAgent(Path(settings.BASE_DIR).parent)

        result = agent.answer("请问《跨片段教程》这篇文章讲了什么？")

        self.assertIn("最终结论", result.answer)
        self.assertIn("full_article_read -> 3 ordered chunks", result.trace)
        self.assertIn("已读取整篇文章", result.answer)

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_blog_agent_resolves_full_article_follow_up_from_history(self):
        article = BlogArticle.objects.create(
            title="会话关联文章",
            slug="conversation-linked-article",
            summary="用于验证会话关联。",
            content="# 第一部分\n内容。\n\n## 最后一部分\n结论。",
            status=BlogArticle.Status.PUBLISHED,
        )
        agent = PublicBlogAgent(Path(settings.BASE_DIR).parent)

        result = agent.answer(
            "那这篇文章讲了什么？",
            history=[{"role": "user", "content": f"我想了解《{article.title}》"}],
        )

        self.assertIn(article.title, result.answer)
        self.assertTrue(any(item.startswith("full_article_read ->") for item in result.trace))

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_full_article_summary_maps_every_chunk_before_reducing(self):
        knowledge_base = KnowledgeBase.objects.create(name="hierarchical summary")
        document = Document.objects.create(
            knowledge_base=knowledge_base,
            title="博客：长文",
            status=Document.Status.READY,
            chunk_count=3,
        )
        markers = ["FIRST_END", "MIDDLE_END", "FINAL_END"]
        for index, marker in enumerate(markers):
            DocumentChunk.objects.create(
                document=document,
                knowledge_base=knowledge_base,
                chunk_index=index,
                content=(chr(65 + index) * 4800) + marker,
            )
        article = BlogArticle.objects.create(
            title="长文",
            slug="long-article",
            content="fallback",
            status=BlogArticle.Status.PUBLISHED,
            knowledge_document=document,
        )
        captured_prompts: list[str] = []

        def fake_llm(prompt_value):
            prompt_text = prompt_value.to_messages()[-1].content
            captured_prompts.append(prompt_text)
            if "全部阶段摘要" in prompt_text:
                return AIMessage(content="完整汇总 [1]")
            return AIMessage(content=f"阶段摘要 {len(captured_prompts)}")

        agent = PublicBlogAgent(Path(settings.BASE_DIR).parent)
        agent.llm = RunnableLambda(fake_llm)

        answer, usage, chunk_count = agent._summarize_full_article(article)

        map_prompts = captured_prompts[:-1]
        self.assertEqual(chunk_count, 3)
        self.assertEqual(len(map_prompts), 3)
        self.assertTrue(all(any(marker in prompt for prompt in map_prompts) for marker in markers))
        self.assertEqual(answer, "完整汇总 [1]")
        self.assertEqual(usage["total_tokens"], 0)

    @patch.dict("os.environ", NO_MODEL_ENV)
    @patch("apps.agent_api.services.rag.search.search_pgvector")
    def test_knowledge_search_prefers_pgvector_candidates_when_available(self, mocked_search_pgvector):
        mocked_search_pgvector.return_value = [
            VectorMatch(
                document_id=9,
                document_title="Vector DB Resume",
                chunk_id=42,
                chunk_index=0,
                content="卫晓斌 教育经历 重庆三峡科技大学 硕士 计算机技术。",
                vector_score=0.93,
            )
        ]

        results = search_knowledge_base("卫晓斌是哪个学校的", limit=3, workspace_key="default")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].chunk_id, 42)
        self.assertIn("重庆三峡科技大学", results[0].content)
        mocked_search_pgvector.assert_called_once()


class QueryEntityExtractionTests(TestCase):
    """B-055：人名后接谓词时不得截断实体，否则知识库检索会完全落空。"""

    SCHOOL_PHRASINGS = (
        "卫晓斌属于哪个学校",
        "卫晓斌来自哪个学校",
        "卫晓斌毕业于哪个学校",
        "卫晓斌就读于哪个学校",
        "卫晓斌的学校",
        "卫晓斌什么学校的",
        "卫晓斌是哪个学校",
        "卫晓斌在哪个学校",
        "卫晓斌是哪所学校的",
        "卫晓斌毕业于哪里",
        "卫晓斌相关信息",
    )

    def test_every_school_phrasing_extracts_the_full_name(self):
        for question in self.SCHOOL_PHRASINGS:
            with self.subTest(question=question):
                self.assertIn("卫晓斌", query_entity_terms(question))

    def test_full_name_ranks_before_truncated_fragment(self):
        # 下游 expand_multilingual_query 只用 entities[0] 生成拼音别名，
        # 必须是完整姓名而不是被截断的「晓斌」。
        self.assertEqual(query_entity_terms("卫晓斌属于哪个学校")[0], "卫晓斌")

    def test_pronoun_only_question_extracts_nothing(self):
        # 「他」需要上游结合对话历史解析；这里不应伪造出「他毕业于」这类实体。
        self.assertEqual(query_entity_terms("他毕业于哪个学校"), [])

    def test_predicate_fragments_are_never_returned_as_entities(self):
        for question in self.SCHOOL_PHRASINGS:
            for entity in query_entity_terms(question):
                with self.subTest(question=question, entity=entity):
                    self.assertFalse(
                        any(entity.endswith(verb) for verb in ("属于", "来自", "毕业于", "就读于")),
                        f"{entity!r} 仍带着谓词尾巴",
                    )


class QueryEntityPreservationTests(TestCase):
    """B-055：LLM 改写丢掉实体时必须回退用原问题检索。"""

    def test_falls_back_when_rewrite_drops_the_name(self):
        from agent.query_rewriting import preserve_query_entities

        original = "卫晓斌属于哪个学校"
        dropped = "Wei Xiaobin university affiliation institution"
        self.assertEqual(preserve_query_entities(original, dropped), original)

    def test_keeps_rewrite_when_entities_survive(self):
        from agent.query_rewriting import preserve_query_entities

        original = "卫晓斌属于哪个学校"
        kept = "卫晓斌 毕业院校 教育背景 Xiaobin Wei"
        self.assertEqual(preserve_query_entities(original, kept), kept)

    def test_passthrough_when_original_has_no_entity(self):
        from agent.query_rewriting import preserve_query_entities

        self.assertEqual(
            preserve_query_entities("这个项目用了什么技术栈", "项目 技术栈 架构"),
            "项目 技术栈 架构",
        )
