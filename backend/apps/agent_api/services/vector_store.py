"""Vector-store adapter for private knowledge-base embeddings.

PostgreSQL deployments use pgvector for durable vector indexing and nearest
neighbor search. SQLite remains a development/test fallback through the Django
EmbeddingRecord table, but production retrieval should go through pgvector.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, connection, models
from rest_framework.exceptions import APIException

from .embedding_space import IDENTITY_FIELDS, EmbeddingSpaceIdentity

PGVECTOR_TABLE = "agent_api_vectorindex"
INDEXED_DIMENSIONS = (384, 1536, 3072)
logger = logging.getLogger(__name__)
_VECTOR_SCHEMA_SQLSTATES = {"42P01", "42703", "42704", "42883"}


class VectorStoreSchemaError(APIException):
    status_code = 503
    default_detail = "The pgvector schema is unavailable or outdated; apply database migrations."
    default_code = "pgvector_schema_unavailable"


class VectorStorePermissionError(APIException):
    status_code = 503
    default_detail = "The database role lacks required pgvector runtime privileges."
    default_code = "pgvector_runtime_privileges_missing"


def _sqlstate(error: BaseException) -> str | None:
    current = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        diag = getattr(current, "diag", None)
        code = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        code = code or getattr(diag, "sqlstate", None)
        if code:
            return str(code)
        current = current.__cause__ or current.__context__
    return None


def _raise_safe_database_error(error: DatabaseError, *, operation: str) -> None:
    """Translate expected schema/permission failures without exposing SQL or credentials."""
    code = _sqlstate(error)
    if code in _VECTOR_SCHEMA_SQLSTATES:
        logger.error("pgvector_schema_unavailable operation=%s sqlstate=%s", operation, code)
        raise VectorStoreSchemaError() from error
    if code == "42501":
        logger.error("pgvector_runtime_privileges_missing operation=%s sqlstate=%s", operation, code)
        raise VectorStorePermissionError() from error
    raise error


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
    if backend == "pgvector":
        if connection.vendor != "postgresql":
            raise ImproperlyConfigured(
                "RAG_VECTOR_BACKEND=pgvector requires a PostgreSQL database; refusing local vector fallback."
            )
        return True
    return connection.vendor == "postgresql"


def vector_literal(vector: Iterable[float]) -> str:
    return "[" + ",".join(f"{float(value):.8g}" for value in vector) + "]"


def upsert_chunk_vector(chunk, identity: EmbeddingSpaceIdentity, vector: list[float]) -> None:
    if not should_use_pgvector():
        return
    metadata = {
        "source": chunk.document.title,
        "chunk_index": chunk.chunk_index,
        **(chunk.metadata or {}),
    }
    with connection.cursor() as cursor:
        try:
            cursor.execute(
                f"""
            INSERT INTO {PGVECTOR_TABLE}
                (chunk_id, document_id, knowledge_base_id, workspace_key,
                 embedding, model, vector_dimensions, metadata, updated_at,
                 provider, model_version, algorithm_version, normalized,
                 corpus_version, index_version, status, fallback_reason, embedded_at)
            VALUES (%s, %s, %s, %s, %s::vector, %s, %s, %s::jsonb, now(),
                    %s, %s, %s, %s, %s, %s, 'ready', '', now())
            ON CONFLICT (chunk_id) DO UPDATE SET
                document_id = EXCLUDED.document_id,
                knowledge_base_id = EXCLUDED.knowledge_base_id,
                workspace_key = EXCLUDED.workspace_key,
                embedding = EXCLUDED.embedding,
                model = EXCLUDED.model,
                vector_dimensions = EXCLUDED.vector_dimensions,
                metadata = EXCLUDED.metadata,
                provider = EXCLUDED.provider,
                model_version = EXCLUDED.model_version,
                algorithm_version = EXCLUDED.algorithm_version,
                normalized = EXCLUDED.normalized,
                corpus_version = EXCLUDED.corpus_version,
                index_version = EXCLUDED.index_version,
                status = 'ready',
                fallback_reason = '',
                embedded_at = now(),
                updated_at = now()
                """,
                [
                    chunk.id,
                    chunk.document_id,
                    chunk.knowledge_base_id,
                    chunk.document.workspace_key,
                    vector_literal(vector),
                    identity.model,
                    identity.vector_dimensions,
                    json.dumps(metadata, ensure_ascii=False),
                    identity.provider,
                    identity.model_version,
                    identity.algorithm_version,
                    identity.normalized,
                    identity.corpus_version,
                    identity.index_version,
                ],
            )
        except DatabaseError as exc:
            _raise_safe_database_error(exc, operation="upsert")


def search_pgvector(
    query_vector: list[float],
    *,
    identity: EmbeddingSpaceIdentity,
    knowledge_base_id: int | None = None,
    workspace_key: str | None = None,
    limit: int = 20,
) -> list[VectorMatch]:
    if not should_use_pgvector():
        return []
    filters: list[str] = ["d.status = 'ready'", "c.ingestion_generation = d.active_ingestion_generation"]
    params: list[object] = []
    dimensions = len(query_vector)
    if dimensions != identity.vector_dimensions:
        raise ValueError("query vector dimensions do not match its embedding-space identity")
    filters.append("v.status = 'ready'")
    for field in IDENTITY_FIELDS:
        filters.append(f"v.{field} = %s")
        params.append(getattr(identity, field))
    if knowledge_base_id:
        filters.append("v.knowledge_base_id = %s")
        params.append(knowledge_base_id)
    if workspace_key:
        filters.append("v.workspace_key = %s")
        params.append(workspace_key)

    query_embedding = vector_literal(query_vector)
    if dimensions == 3072:
        distance_sql = "(v.embedding::halfvec(3072) <=> %s::halfvec(3072))"
    elif dimensions in INDEXED_DIMENSIONS:
        distance_sql = f"(v.embedding::vector({dimensions}) <=> %s::vector({dimensions}))"
    else:
        distance_sql = "(v.embedding <=> %s::vector)"
    where_sql = " AND ".join(filters)
    with connection.cursor() as cursor:
        try:
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
        except DatabaseError as exc:
            _raise_safe_database_error(exc, operation="search")

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


def count_incompatible_embeddings(
    identity: EmbeddingSpaceIdentity,
    *,
    knowledge_base_id: int | None = None,
    workspace_key: str | None = None,
) -> int:
    """Count scoped vectors excluded by status or identity; emit no source text."""
    if should_use_pgvector():
        identity_fields = []
        for field in IDENTITY_FIELDS:
            identity_fields.append(f"v.{field} = %s")
        mismatch_sql = " OR ".join(["v.status <> 'ready'", *[f"NOT ({item})" for item in identity_fields]])
        query_params: list[object] = []
        if knowledge_base_id:
            query_params.append(knowledge_base_id)
        if workspace_key:
            query_params.append(workspace_key)
        with connection.cursor() as cursor:
            try:
                cursor.execute(
                    f"""
                SELECT COUNT(*)
                FROM {PGVECTOR_TABLE} v
                JOIN agent_api_document d ON d.id = v.document_id
                JOIN agent_api_documentchunk c ON c.id = v.chunk_id
                WHERE d.status = 'ready'
                  AND c.ingestion_generation = d.active_ingestion_generation
                  AND ({'v.knowledge_base_id = %s AND ' if knowledge_base_id else ''}
                       {'v.workspace_key = %s AND ' if workspace_key else ''}({mismatch_sql}))
                    """,
                    [*query_params, *[getattr(identity, field) for field in IDENTITY_FIELDS]],
                )
                return int(cursor.fetchone()[0])
            except DatabaseError as exc:
                _raise_safe_database_error(exc, operation="audit")

    from ..models import EmbeddingRecord

    records = EmbeddingRecord.objects.filter(
        chunk__document__status="ready",
        chunk__ingestion_generation=models.F("chunk__document__active_ingestion_generation"),
    )
    if knowledge_base_id:
        records = records.filter(chunk__knowledge_base_id=knowledge_base_id)
    if workspace_key:
        records = records.filter(chunk__knowledge_base__workspace_key=workspace_key)
    exact = {"status": "ready", **identity.as_record_fields()}
    return int(records.exclude(**exact).count())
