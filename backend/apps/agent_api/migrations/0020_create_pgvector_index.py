import json

from django.db import migrations


def vector_literal(vector):
    return "[" + ",".join(f"{float(value):.8g}" for value in vector) + "]"


def create_pgvector_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_api_vectorindex (
                chunk_id bigint PRIMARY KEY
                    REFERENCES agent_api_documentchunk(id) ON DELETE CASCADE,
                document_id bigint NOT NULL
                    REFERENCES agent_api_document(id) ON DELETE CASCADE,
                knowledge_base_id bigint NOT NULL
                    REFERENCES agent_api_knowledgebase(id) ON DELETE CASCADE,
                workspace_key varchar(80) NOT NULL,
                embedding vector NOT NULL,
                model varchar(120) NOT NULL,
                vector_dimensions integer NOT NULL,
                metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
                updated_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS agent_api_vectorindex_workspace_kb_idx
            ON agent_api_vectorindex (workspace_key, knowledge_base_id)
            """
        )
        for dimensions in (384, 1536, 3072):
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS agent_api_vectorindex_embedding_{dimensions}_hnsw_idx
                ON agent_api_vectorindex
                USING hnsw ((embedding::vector({dimensions})) vector_cosine_ops)
                WHERE vector_dimensions = {dimensions}
                """
            )

        EmbeddingRecord = apps.get_model("agent_api", "EmbeddingRecord")
        for record in EmbeddingRecord.objects.select_related("chunk", "chunk__document").iterator():
            if not record.vector:
                continue
            chunk = record.chunk
            document = chunk.document
            metadata = {
                "source": document.title,
                "chunk_index": chunk.chunk_index,
                **(chunk.metadata or {}),
            }
            cursor.execute(
                """
                INSERT INTO agent_api_vectorindex
                    (chunk_id, document_id, knowledge_base_id, workspace_key,
                     embedding, model, vector_dimensions, metadata, updated_at)
                VALUES (%s, %s, %s, %s, %s::vector, %s, %s, %s::jsonb, now())
                ON CONFLICT (chunk_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id,
                    knowledge_base_id = EXCLUDED.knowledge_base_id,
                    workspace_key = EXCLUDED.workspace_key,
                    embedding = EXCLUDED.embedding,
                    model = EXCLUDED.model,
                    vector_dimensions = EXCLUDED.vector_dimensions,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                """,
                [
                    chunk.id,
                    chunk.document_id,
                    chunk.knowledge_base_id,
                    document.workspace_key,
                    vector_literal(record.vector),
                    record.model,
                    record.vector_dimensions or len(record.vector),
                    json.dumps(metadata, ensure_ascii=False),
                ],
            )


def drop_pgvector_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS agent_api_vectorindex")


class Migration(migrations.Migration):
    dependencies = [
        ("agent_api", "0019_scope_knowledge_base_name_to_workspace"),
    ]

    operations = [
        migrations.RunPython(create_pgvector_index, drop_pgvector_index),
    ]
