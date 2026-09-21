"""Vector-store adapter for private knowledge-base embeddings.

PostgreSQL deployments use pgvector for durable vector indexing and nearest
neighbor search. SQLite remains a development/test fallback through the Django
EmbeddingRecord table, but production retrieval should go through pgvector.
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import Iterable

from django.db import connection


PGVECTOR_TABLE = "agent_api_vectorindex"
INDEXED_DIMENSIONS = (384, 1536, 3072)


@dataclass(frozen=True)
class VectorMatch:
    document_id: int
    document_title: str
    chunk_id: int
    chunk_index: int
    content: str
    vector_score: float


def vector_backend() -> str:
    return os.getenv("RAG_VECTOR_BACKEND", "auto").strip().lower() or "auto"


def should_use_pgvector() -> bool:
    backend = vector_backend()
    if backend in {"django", "sqlite", "json", "legacy"}:
        return False
    if backend == "pgvector" and connection.vendor != "postgresql":
        return False
    return connection.vendor == "postgresql"


def vector_literal(vector: Iterable[float]) -> str:
    return "[" + ",".join(f"{float(value):.8g}" for value in vector) + "]"


def ensure_pgvector_schema() -> None:
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {PGVECTOR_TABLE} (
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
                metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                updated_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS agent_api_vectorindex_workspace_kb_idx
            ON {PGVECTOR_TABLE} (workspace_key, knowledge_base_id)
            """
        )
        for dimensions in INDEXED_DIMENSIONS:
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS agent_api_vectorindex_embedding_{dimensions}_hnsw_idx
                ON {PGVECTOR_TABLE}
                USING hnsw ((embedding::vector({dimensions})) vector_cosine_ops)
                WHERE vector_dimensions = {dimensions}
                """
            )


def upsert_chunk_vector(chunk, model: str, vector: list[float]) -> None:
    if not should_use_pgvector():
        return
    ensure_pgvector_schema()
    metadata = {
        "source": chunk.document.title,
        "chunk_index": chunk.chunk_index,
        **(chunk.metadata or {}),
    }
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {PGVECTOR_TABLE}
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
                chunk.document.workspace_key,
                vector_literal(vector),
                model,
                len(vector),
                json.dumps(metadata, ensure_ascii=False),
            ],
        )


def search_pgvector(
    query_vector: list[float],
    *,
    knowledge_base_id: int | None = None,
    workspace_key: str | None = None,
    limit: int = 20,
) -> list[VectorMatch]:
    if not should_use_pgvector():
        return []
    ensure_pgvector_schema()
    filters: list[str] = ["d.status = 'ready'"]
    params: list[object] = []
    dimensions = len(query_vector)
    filters.append("v.vector_dimensions = %s")
    params.append(dimensions)
    if knowledge_base_id:
        filters.append("v.knowledge_base_id = %s")
        params.append(knowledge_base_id)
    if workspace_key:
        filters.append("v.workspace_key = %s")
        params.append(workspace_key)

    query_embedding = vector_literal(query_vector)
    if dimensions in INDEXED_DIMENSIONS:
        distance_sql = f"(v.embedding::vector({dimensions}) <=> %s::vector({dimensions}))"
    else:
        distance_sql = "(v.embedding <=> %s::vector)"
    where_sql = " AND ".join(filters)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                d.id,
                d.title,
                c.id,
                c.chunk_index,
                c.content,
                GREATEST(0, 1 - {distance_sql}) AS vector_score
            FROM {PGVECTOR_TABLE} v
            JOIN agent_api_documentchunk c ON c.id = v.chunk_id
            JOIN agent_api_document d ON d.id = v.document_id
            WHERE {where_sql}
            ORDER BY {distance_sql}
            LIMIT %s
            """,
            [query_embedding, *params, query_embedding, limit],
        )
        rows = cursor.fetchall()

    return [
        VectorMatch(
            document_id=row[0],
            document_title=row[1],
            chunk_id=row[2],
            chunk_index=row[3],
            content=row[4],
            vector_score=float(row[5] or 0.0),
        )
        for row in rows
    ]
