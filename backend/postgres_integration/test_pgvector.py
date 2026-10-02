"""Real PostgreSQL/pgvector integration tests; SQLite must never run this suite."""

from unittest.mock import patch
from uuid import uuid4

from django.db import DatabaseError, connection, transaction
from django.test import TestCase, TransactionTestCase

from apps.agent_api.models import Document, DocumentChunk, EmbeddingRecord, KnowledgeBase
from apps.agent_api.services.embedding_space import EmbeddingSpaceIdentity
from apps.agent_api.services.rag.search import search_knowledge_base
from apps.agent_api.services.vector_store import (
    PGVECTOR_TABLE,
    VectorStorePermissionError,
    VectorStoreSchemaError,
    _sqlstate,
    count_incompatible_embeddings,
    search_pgvector,
    should_use_pgvector,
    upsert_chunk_vector,
)


class PgVectorPostgresIntegrationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if connection.vendor != "postgresql":
            raise AssertionError("pgvector integration tests require PostgreSQL; SQLite fallback is forbidden")
        if not should_use_pgvector():
            raise AssertionError("RAG_VECTOR_BACKEND=pgvector must select the PostgreSQL vector store")

    def identity(self, dimensions: int, model="integration-model-a", model_version="v1"):
        return EmbeddingSpaceIdentity(
            provider="test-provider",
            model=model,
            model_version=model_version,
            algorithm_version="test-algorithm-v1",
            vector_dimensions=dimensions,
            normalized=False,
            corpus_version="fixture-corpus-v1",
            index_version="fixture-index-v1",
        )

    def make_chunk(self, workspace_key: str, name: str, content: str, vector: list[float], identity=None):
        identity = identity or self.identity(len(vector))
        knowledge_base = KnowledgeBase.objects.create(name=name, workspace_key=workspace_key)
        document = Document.objects.create(
            knowledge_base=knowledge_base,
            workspace_key=workspace_key,
            title=name,
            content_text=content,
            status=Document.Status.READY,
            chunk_count=1,
        )
        chunk = DocumentChunk.objects.create(
            document=document,
            knowledge_base=knowledge_base,
            chunk_index=0,
            content=content,
        )
        EmbeddingRecord.objects.create(
            chunk=chunk,
            vector=[],
            status=EmbeddingRecord.Status.READY,
            **identity.as_record_fields(),
        )
        upsert_chunk_vector(chunk, identity, vector)
        return document, chunk

    def test_vector_runtime_hot_paths_issue_no_schema_ddl(self):
        knowledge_base = KnowledgeBase.objects.create(name="ddl observation", workspace_key="ddl-workspace")
        document = Document.objects.create(
            knowledge_base=knowledge_base,
            workspace_key="ddl-workspace",
            title="DDL observation",
            status=Document.Status.READY,
        )
        chunk = DocumentChunk.objects.create(
            document=document,
            knowledge_base=knowledge_base,
            chunk_index=0,
            content="runtime DDL observation",
        )
        identity = self.identity(3)
        EmbeddingRecord.objects.create(
            chunk=chunk, vector=[], status=EmbeddingRecord.Status.READY, **identity.as_record_fields()
        )
        runtime_ddl = []

        def capture_sql(execute, sql, params, many, context):
            statement = sql.lstrip().upper()
            if statement.startswith(("CREATE ", "ALTER ", "DROP ", "TRUNCATE ", "COMMENT ")):
                runtime_ddl.append(sql.strip().splitlines()[0])
            return execute(sql, params, many, context)

        with connection.execute_wrapper(capture_sql):
            upsert_chunk_vector(chunk, identity, [1.0, 0.0, 0.0])
            search_pgvector([1.0, 0.0, 0.0], identity=identity, workspace_key="ddl-workspace")
            count_incompatible_embeddings(identity, workspace_key="ddl-workspace")
            document.delete()

        self.assertEqual(runtime_ddl, [], f"runtime data paths executed schema DDL: {runtime_ddl}")

    def test_missing_or_outdated_schema_fails_with_safe_migration_error(self):
        knowledge_base = KnowledgeBase.objects.create(name="missing schema", workspace_key="missing-schema")
        document = Document.objects.create(
            knowledge_base=knowledge_base,
            workspace_key="missing-schema",
            title="missing schema",
            status=Document.Status.READY,
        )
        chunk = DocumentChunk.objects.create(
            document=document,
            knowledge_base=knowledge_base,
            chunk_index=0,
            content="schema is intentionally missing",
        )
        identity = self.identity(3)
        with patch("apps.agent_api.services.vector_store.PGVECTOR_TABLE", "agent_api_b013_missing_table"):
            with self.assertRaises(VectorStoreSchemaError) as caught:
                with transaction.atomic():
                    search_pgvector([1.0, 0.0, 0.0], identity=identity)
            self.assertIn("apply database migrations", str(caught.exception.detail))

            with self.assertRaises(VectorStoreSchemaError):
                with transaction.atomic():
                    upsert_chunk_vector(chunk, identity, [1.0, 0.0, 0.0])

    def test_runtime_role_without_create_or_alter_can_read_write_and_delete_vectors(self):
        knowledge_base = KnowledgeBase.objects.create(name="limited role", workspace_key="limited-role")
        document = Document.objects.create(
            knowledge_base=knowledge_base,
            workspace_key="limited-role",
            title="limited role fixture",
            content_text="a limited PostgreSQL role can use the migrated vector schema",
            status=Document.Status.READY,
        )
        chunk = DocumentChunk.objects.create(
            document=document,
            knowledge_base=knowledge_base,
            chunk_index=0,
            content=document.content_text,
        )
        identity = self.identity(3)
        role = f"b013_runtime_{uuid4().hex}"
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE ROLE {role} NOLOGIN")
            cursor.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
            cursor.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {PGVECTOR_TABLE} TO {role}")
            cursor.execute(
                f"GRANT SELECT ON agent_api_document, agent_api_documentchunk, agent_api_knowledgebase TO {role}"
            )

        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SET LOCAL ROLE {role}")
                cursor.execute("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
                self.assertFalse(cursor.fetchone()[0])

            upsert_chunk_vector(chunk, identity, [1.0, 0.0, 0.0])
            upsert_chunk_vector(chunk, identity, [0.0, 1.0, 0.0])
            matches = search_pgvector([0.0, 1.0, 0.0], identity=identity, workspace_key="limited-role")
            self.assertEqual([item.document_id for item in matches], [document.pk])
            self.assertEqual(count_incompatible_embeddings(identity, workspace_key="limited-role"), 0)

            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {PGVECTOR_TABLE} WHERE chunk_id = %s", [chunk.pk])
                self.assertEqual(cursor.rowcount, 1)
            self.assertEqual(search_pgvector([1.0, 0.0, 0.0], identity=identity), [])

            forbidden_ddl = (
                f"CREATE TABLE public.{role}_must_fail (id integer)",
                f"ALTER TABLE {PGVECTOR_TABLE} ADD COLUMN {role}_must_fail integer",
            )
            for statement in forbidden_ddl:
                with self.assertRaises(DatabaseError) as caught:
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute(statement)
                self.assertEqual(_sqlstate(caught.exception), "42501")
        except VectorStorePermissionError as exc:
            self.fail(f"runtime DML unexpectedly required schema privileges: {exc.detail}")
        finally:
            with connection.cursor() as cursor:
                cursor.execute("RESET ROLE")
                cursor.execute(f"DROP OWNED BY {role}")
                cursor.execute(f"DROP ROLE {role}")

    def test_empty_database_migrations_install_pgvector_table_and_indexes(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('server_version_num'), extversion FROM pg_extension WHERE extname = 'vector'"
            )
            server_version_num, extension_version = cursor.fetchone()
            cursor.execute("SELECT to_regclass(%s)", [PGVECTOR_TABLE])
            vector_table = cursor.fetchone()[0]
            cursor.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = %s", [PGVECTOR_TABLE])
            indexes = dict(cursor.fetchall())

        server_major = int(server_version_num) // 10000
        self.assertEqual(server_major, 16)
        self.assertEqual(extension_version, "0.8.6")
        self.assertIsNotNone(vector_table)
        self.assertIn("agent_api_vectorindex_workspace_kb_idx", indexes)
        self.assertIn("agent_api_vectorindex_embedding_384_hnsw_idx", indexes)
        self.assertIn("agent_api_vectorindex_embedding_1536_hnsw_idx", indexes)
        self.assertIn("agent_api_vectorindex_embedding_3072_halfvec_hnsw_idx", indexes)
        self.assertIn("agent_api_vectorindex_space_filter_idx", indexes)
        self.assertNotIn("agent_api_vectorindex_embedding_3072_hnsw_idx", indexes)
        self.assertIn("halfvec", indexes["agent_api_vectorindex_embedding_3072_halfvec_hnsw_idx"])
        print(
            f"PostgreSQL {server_version_num}; pgvector {extension_version}; migrated {PGVECTOR_TABLE} with 4 indexes"
        )

    def test_vector_write_search_update_delete_and_workspace_isolation(self):
        identity_a = self.identity(3)
        identity_b = self.identity(3, model="integration-model-b", model_version="v1")
        alpha_doc, alpha_chunk = self.make_chunk(
            "workspace-alpha", "alpha fixture", "alpha pgvector integration marker", [1.0, 0.0, 0.0], identity_a
        )
        beta_doc, _ = self.make_chunk(
            "workspace-beta", "beta fixture", "beta pgvector integration marker", [1.0, 0.0, 0.0], identity_a
        )
        incompatible_doc, _ = self.make_chunk(
            "workspace-alpha",
            "incompatible model",
            "must not match same-dimension different-model vector",
            [1.0, 0.0, 0.0],
            identity_b,
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT embedding::text, model, vector_dimensions, provider, model_version, status FROM {PGVECTOR_TABLE} WHERE chunk_id = %s",
                [alpha_chunk.pk],
            )
            self.assertEqual(cursor.fetchone(), ("[1,0,0]", "integration-model-a", 3, "test-provider", "v1", "ready"))

        alpha_matches = search_pgvector([1.0, 0.0, 0.0], identity=identity_a, workspace_key="workspace-alpha")
        beta_matches = search_pgvector([1.0, 0.0, 0.0], identity=identity_a, workspace_key="workspace-beta")
        self.assertEqual([match.document_id for match in alpha_matches], [alpha_doc.pk])
        self.assertEqual([match.document_id for match in beta_matches], [beta_doc.pk])
        model_b_matches = search_pgvector([1.0, 0.0, 0.0], identity=identity_b, workspace_key="workspace-alpha")
        self.assertEqual([match.document_id for match in model_b_matches], [incompatible_doc.pk])
        self.assertEqual(sum(match.document_id in {alpha_doc.pk, incompatible_doc.pk} for match in alpha_matches), 1)
        self.assertEqual(
            count_incompatible_embeddings(identity_a, workspace_key="workspace-alpha"),
            1,
            "same-dimension vectors from a different model must be observable as incompatible",
        )

        identity_a_v2 = self.identity(3, model_version="v2")
        upsert_chunk_vector(alpha_chunk, identity_a_v2, [0.0, 1.0, 0.0])
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT embedding::text, model, vector_dimensions, model_version FROM {PGVECTOR_TABLE} WHERE chunk_id = %s",
                [alpha_chunk.pk],
            )
            self.assertEqual(cursor.fetchone(), ("[0,1,0]", "integration-model-a", 3, "v2"))
        self.assertFalse(search_pgvector([1.0, 0.0, 0.0], identity=identity_a, workspace_key="workspace-alpha"))
        self.assertEqual(count_incompatible_embeddings(identity_a, workspace_key="workspace-alpha"), 2)
        updated_matches = search_pgvector([0.0, 1.0, 0.0], identity=identity_a_v2, workspace_key="workspace-alpha")
        self.assertEqual([match.document_id for match in updated_matches], [alpha_doc.pk])

        alpha_doc.delete()
        self.assertFalse(search_pgvector([0.0, 1.0, 0.0], identity=identity_a_v2, workspace_key="workspace-alpha"))
        self.assertEqual(
            [
                match.document_id
                for match in search_pgvector([1.0, 0.0, 0.0], identity=identity_a, workspace_key="workspace-beta")
            ],
            [beta_doc.pk],
        )

    def test_3072_dimension_uses_halfvec_and_mismatch_returns_no_result_without_fallback(self):
        vector = [1.0] + [0.0] * 3071
        identity = self.identity(3072)
        document, _ = self.make_chunk("workspace-3072", "3072 fixture", "half precision index marker", vector, identity)
        matches = search_pgvector(vector, identity=identity, workspace_key="workspace-3072")
        self.assertEqual([match.document_id for match in matches], [document.pk])

        # A different query dimension is safely filtered to no result. On a
        # PostgreSQL backend, the JSON/local fallback must not mask that result.
        with patch("apps.agent_api.services.rag.search.embed_query", return_value=[1.0, 0.0]):
            with patch(
                "apps.agent_api.services.rag.search.search_knowledge_base_with_django_vectors",
                side_effect=AssertionError("PostgreSQL search must never fall back to Django JSON vectors"),
            ):
                self.assertEqual(search_knowledge_base("mismatch", workspace_key="workspace-3072"), [])


class PgVectorOutboxCommitTests(TransactionTestCase):
    def test_outbox_message_is_published_after_postgresql_commit(self):
        if connection.vendor != "postgresql":
            raise AssertionError("outbox commit integration requires PostgreSQL")
        from apps.agent_api.models import DocumentIngestionJob
        from apps.agent_api.services.ingestion_jobs import schedule_document_ingestion

        base = KnowledgeBase.objects.create(name="outbox commit pg", workspace_key="pg-outbox")
        document = Document.objects.create(
            knowledge_base=base,
            workspace_key="pg-outbox",
            title="commit check",
            content_text="committed source text",
        )
        observed = []

        def observe(job_id):
            self.assertFalse(connection.in_atomic_block)
            observed.append(
                DocumentIngestionJob.objects.filter(
                    pk=job_id,
                    document__content_text="committed source text",
                ).exists()
            )

        with patch("apps.agent_api.services.ingestion_jobs.dispatch_ingestion_job", side_effect=observe):
            with transaction.atomic():
                job = schedule_document_ingestion(document)
                self.assertEqual(observed, [])
            self.assertEqual(observed, [True])
        self.assertEqual(job.status, DocumentIngestionJob.Status.PENDING)

    def test_vector_query_only_exposes_the_document_active_generation(self):
        if connection.vendor != "postgresql":
            raise AssertionError("generation integration requires PostgreSQL")
        workspace = f"generation-{uuid4().hex}"
        base = KnowledgeBase.objects.create(name="generation switch", workspace_key=workspace)
        document = Document.objects.create(
            knowledge_base=base,
            workspace_key=workspace,
            title="generation switch",
            content_text="old generation text",
            status=Document.Status.READY,
            chunk_count=1,
        )
        identity = EmbeddingSpaceIdentity(
            provider="test-provider",
            model="generation-model",
            model_version="v1",
            algorithm_version="test-algorithm-v1",
            vector_dimensions=3,
            normalized=False,
            corpus_version="fixture-corpus-v1",
            index_version="fixture-index-v1",
        )

        def add_chunk(generation, content, vector):
            chunk = DocumentChunk.objects.create(
                document=document,
                knowledge_base=base,
                ingestion_generation=generation,
                chunk_index=0,
                content=content,
            )
            EmbeddingRecord.objects.create(
                chunk=chunk, vector=[], status=EmbeddingRecord.Status.READY, **identity.as_record_fields()
            )
            upsert_chunk_vector(chunk, identity, vector)
            return chunk

        old_chunk = add_chunk(0, "old active", [1.0, 0.0, 0.0])
        new_chunk = add_chunk(1, "new staged", [0.0, 1.0, 0.0])
        self.assertEqual(
            [item.chunk_id for item in search_pgvector([1.0, 0.0, 0.0], identity=identity, workspace_key=workspace)],
            [old_chunk.pk],
        )
        Document.objects.filter(pk=document.pk).update(active_ingestion_generation=1)
        self.assertEqual(
            [item.chunk_id for item in search_pgvector([0.0, 1.0, 0.0], identity=identity, workspace_key=workspace)],
            [new_chunk.pk],
        )
