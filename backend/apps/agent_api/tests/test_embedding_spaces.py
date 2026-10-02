"""Embedding identity, failure and reindex safety regressions."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from ..models import Document, DocumentChunk, DocumentIngestionJob, EmbeddingRecord, KnowledgeBase
from ..services.embedding_space import EmbeddingSpaceError, embedding_space_identity
from ..services.ingestion_jobs import process_ingestion_job, schedule_document_ingestion
from ..services.rag.ingest import EmbeddingRequestError, embed_texts, ingest_document
from ..services.rag.search import search_knowledge_base
from ..services.rag.text import local_embedding


class EmbeddingSpaceTests(TestCase):
    def setUp(self):
        self.knowledge_base = KnowledgeBase.objects.create(name="embedding space tests")
        self.document = Document.objects.create(
            knowledge_base=self.knowledge_base,
            title="Known indexed document",
            content_text="A previously indexed fact stays available during a provider outage.",
            status=Document.Status.READY,
            chunk_count=1,
        )
        self.chunk = DocumentChunk.objects.create(
            document=self.document,
            knowledge_base=self.knowledge_base,
            chunk_index=0,
            content=self.document.content_text,
        )
        identity = embedding_space_identity(384, mode="local_hash")
        EmbeddingRecord.objects.create(
            chunk=self.chunk,
            vector=local_embedding(self.chunk.content),
            status=EmbeddingRecord.Status.READY,
            **identity.as_record_fields(),
        )

    @patch.dict(
        "os.environ",
        {
            "RAG_EMBEDDING_MODE": "remote",
            "RAG_EMBEDDING_MODEL_VERSION": "provider-release-2026-09",
            "BAILIAN_API_KEY": "test-only-secret",
            "BAILIAN_EMBEDDING_MODEL": "text-embedding-v1",
            "BAILIAN_EMBEDDING_BASE_URL": "https://provider.example/v1",
        },
        clear=True,
    )
    @patch("apps.agent_api.services.rag.ingest.local_embedding")
    @patch("apps.agent_api.services.rag.ingest.OpenAIEmbeddings")
    def test_provider_failure_is_not_silently_replaced_by_local_hash(self, embeddings, mocked_local):
        embeddings.return_value.embed_documents.side_effect = RuntimeError("secret-token-must-not-be-logged")

        with self.assertRaises(EmbeddingRequestError):
            embed_texts(["test query"])

        mocked_local.assert_not_called()

    @patch.dict("os.environ", {"RAG_EMBEDDING_MODE": "remote"}, clear=True)
    def test_remote_space_requires_a_pinned_model_version(self):
        with self.assertRaisesMessage(EmbeddingSpaceError, "RAG_EMBEDDING_MODEL_VERSION is required"):
            embedding_space_identity(1536)

    def test_provider_failure_is_marked_retryable_even_when_prior_index_stays_ready(self):
        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job"):
            job = schedule_document_ingestion(self.document, force=True)
        with patch(
            "apps.agent_api.services.rag.ingest.build_document_index", side_effect=EmbeddingRequestError("RuntimeError")
        ):
            result = process_ingestion_job(str(job.pk))
        job.refresh_from_db()
        self.document.refresh_from_db()
        self.assertEqual(result["status"], DocumentIngestionJob.Status.RETRY)
        self.assertEqual(job.status, DocumentIngestionJob.Status.RETRY)
        self.assertEqual(job.failure_code, "embedding_request_failed:RuntimeError")
        self.assertEqual(self.document.status, Document.Status.READY)
        self.assertEqual(self.document.chunks.get().pk, self.chunk.pk)

    def test_legacy_identity_audit_quarantines_without_deleting_vector(self):
        legacy_chunk = DocumentChunk.objects.create(
            document=self.document,
            knowledge_base=self.knowledge_base,
            chunk_index=1,
            content="legacy vector must be retained",
        )
        legacy = EmbeddingRecord.objects.create(
            chunk=legacy_chunk,
            model="old-model",
            model_version="unknown",
            vector=[0.25, 0.5],
            vector_dimensions=2,
            status=EmbeddingRecord.Status.READY,
        )

        call_command("audit_embedding_spaces", "--quarantine-unknown", stdout=StringIO())

        legacy.refresh_from_db()
        self.assertEqual(legacy.status, EmbeddingRecord.Status.QUARANTINED)
        self.assertEqual(legacy.vector, [0.25, 0.5])

    @patch.dict(
        "os.environ",
        {
            "RAG_EMBEDDING_MODE": "remote",
            "RAG_EMBEDDING_MODEL_VERSION": "provider-release-2026-09",
            "BAILIAN_API_KEY": "test-only-secret",
            "BAILIAN_EMBEDDING_MODEL": "text-embedding-v1",
            "BAILIAN_EMBEDDING_BASE_URL": "https://provider.example/v1",
        },
        clear=True,
    )
    @patch("apps.agent_api.services.rag.ingest.OpenAIEmbeddings")
    def test_failed_reindex_retains_previous_ready_chunks_without_leaking_provider_detail(self, embeddings):
        embeddings.return_value.embed_documents.side_effect = RuntimeError("secret-token-must-not-be-saved")

        result = ingest_document(self.document)

        self.assertEqual(result.status, Document.Status.READY)
        self.assertEqual(result.chunks.get().pk, self.chunk.pk)
        self.assertTrue(result.error_message.startswith("embedding_request_failed:RuntimeError"))
        self.assertNotIn("secret-token", result.error_message)
        self.assertEqual(EmbeddingRecord.objects.get(chunk=self.chunk).status, EmbeddingRecord.Status.READY)

    @patch.dict("os.environ", {"RAG_EMBEDDING_MODE": "local_hash"}, clear=True)
    def test_local_hash_is_explicit_and_retrieval_excludes_other_identity(self):
        results = search_knowledge_base(
            "previously indexed fact",
            knowledge_base_id=self.knowledge_base.pk,
            workspace_key=self.document.workspace_key,
        )
        self.assertEqual([result.document_id for result in results], [self.document.pk])

        other_space = type(embedding_space_identity(384, mode="local_hash"))(
            provider="another-provider",
            model="same-dimension-different-model",
            model_version="v1",
            algorithm_version="provider-api-v1",
            vector_dimensions=384,
            normalized=True,
            corpus_version="corpus-v1",
            index_version="index-v1",
        )
        other_doc = Document.objects.create(
            knowledge_base=self.knowledge_base,
            title="Same dimensions, other model",
            content_text="A second model must not appear in local-hash retrieval.",
            status=Document.Status.READY,
        )
        other_chunk = DocumentChunk.objects.create(
            document=other_doc,
            knowledge_base=self.knowledge_base,
            chunk_index=0,
            content=other_doc.content_text,
        )
        EmbeddingRecord.objects.create(
            chunk=other_chunk,
            vector=local_embedding(other_chunk.content),
            status=EmbeddingRecord.Status.READY,
            **other_space.as_record_fields(),
        )
        results = search_knowledge_base(
            "previously indexed fact",
            knowledge_base_id=self.knowledge_base.pk,
            workspace_key=self.document.workspace_key,
        )
        self.assertEqual([result.document_id for result in results], [self.document.pk])

        incompatible_identity = embedding_space_identity(384, mode="local_hash")
        incompatible_identity = type(incompatible_identity)(
            **{
                **incompatible_identity.as_record_fields(),
                "index_version": "future-index-v2",
            }
        )
        with (
            patch("apps.agent_api.services.rag.search.embed_query", return_value=[0.0] * 384),
            patch("apps.agent_api.services.rag.search.embedding_space_identity", return_value=incompatible_identity),
        ):
            mismatched = search_knowledge_base(
                "previously indexed fact",
                knowledge_base_id=self.knowledge_base.pk,
                workspace_key=self.document.workspace_key,
            )
        self.assertEqual(mismatched, [])
