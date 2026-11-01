"""RAG 入库管线：文本抽取、切分、embedding 与原子化写库。"""

from __future__ import annotations

import logging
import math
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from django.db import transaction
from django.utils import timezone
from langchain_openai import OpenAIEmbeddings

from agent.telemetry import observe_stage

from ...models import Document, DocumentChunk, EmbeddingRecord, KnowledgeBase
from ...models.constants import DEFAULT_WORKSPACE_KEY
from ..embedding_space import (
    EmbeddingSpaceError,
    embedding_mode,
    embedding_space_identity,
    normalize_vector,
)
from ..vector_store import should_use_pgvector, upsert_chunk_vector
from .text import local_embedding, normalize_text

DEFAULT_KNOWLEDGE_BASE_NAME = "默认知识库"
DEFAULT_BAILIAN_EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_BAILIAN_EMBEDDING_MODEL = "text-embedding-v1"
LOCAL_EMBEDDING_MODEL = "local-hash-embedding"
logger = logging.getLogger(__name__)
CHUNK_SIZE = 900
CHUNK_OVERLAP = 140


def get_default_knowledge_base(workspace_key: str = DEFAULT_WORKSPACE_KEY) -> KnowledgeBase:
    knowledge_base, _ = KnowledgeBase.objects.get_or_create(
        name=DEFAULT_KNOWLEDGE_BASE_NAME,
        workspace_key=workspace_key,
        defaults={"description": "Day4 本地知识库，用于上传文档、切分、向量检索和 Agent RAG。"},
    )
    return knowledge_base


def extract_text_from_document(document: Document) -> str:
    if document.content_text.strip():
        return document.content_text

    path = Path(document.source_file.path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_text(path)
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF 解析需要安装 pypdf。") from exc

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(page.strip() for page in pages if page.strip())


def split_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    paragraphs = [item.strip() for item in re.split(r"\n{2,}", normalized) if item.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(split_long_text(paragraph, chunk_size, overlap))
            continue

        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            chunks.append(current.strip())
            current = paragraph

    if current:
        chunks.append(current.strip())

    return chunks


def split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return [chunk for chunk in chunks if chunk]


def ingest_document(document: Document) -> Document:
    """Compatibility helper for direct callers; provider work precedes index replacement."""
    try:
        chunks, vectors, identity = build_document_index(document)
        generation = document.desired_ingestion_generation or document.active_ingestion_generation or 1
        with transaction.atomic():
            persist_document_index(document, chunks, vectors, identity, generation=generation)
            document.chunks.exclude(ingestion_generation=generation).delete()
            document.active_ingestion_generation = generation
            document.desired_ingestion_generation = max(document.desired_ingestion_generation, generation)
            document.status = Document.Status.READY
            document.chunk_count = len(chunks)
            document.ingestion_error_code = ""
            document.error_message = ""
            document.save(
                update_fields=[
                    "active_ingestion_generation",
                    "desired_ingestion_generation",
                    "status",
                    "chunk_count",
                    "ingestion_error_code",
                    "error_message",
                    "updated_at",
                ]
            )
    except EmbeddingSpaceError as exc:
        failure_code = getattr(exc, "failure_code", "embedding_space_invalid")
        document.ingestion_error_code = failure_code[:80]
        document.error_message = failure_code[:300]
        has_previous_index = (
            document.status == Document.Status.READY
            and document.chunks.filter(ingestion_generation=document.active_ingestion_generation).exists()
        )
        logger.warning(
            "rag_embedding_failed document_id=%s failure_code=%s retained_previous_index=%s",
            document.pk,
            failure_code,
            has_previous_index,
        )
        if not has_previous_index:
            document.status = Document.Status.FAILED
        document.save(update_fields=["status", "ingestion_error_code", "error_message", "updated_at"])
    except Exception:
        document.ingestion_error_code = "document_ingestion_failed"
        document.error_message = "document_ingestion_failed"
        has_previous_index = (
            document.status == Document.Status.READY
            and document.chunks.filter(ingestion_generation=document.active_ingestion_generation).exists()
        )
        if not has_previous_index:
            document.status = Document.Status.FAILED
        document.save(update_fields=["status", "ingestion_error_code", "error_message", "updated_at"])
    return document


def build_document_index(document: Document):
    """Do file parsing and all embedding I/O before opening the short write transaction."""
    text = extract_text_from_document(document)
    chunks = split_text(text)
    if not chunks:
        raise ValueError("文档没有可索引的文本内容。")
    vectors = embed_texts(chunks)
    mode = embedding_mode()
    base_url = normalized_embedding_base_url() if mode == "remote" else ""
    model_name = embedding_model() if mode == "remote" else LOCAL_EMBEDDING_MODEL
    identity = embedding_space_identity(len(vectors[0]), mode=mode, model=model_name, base_url=base_url)
    if any(len(vector) != identity.vector_dimensions for vector in vectors):
        raise EmbeddingSpaceError("Embedding service returned vectors with inconsistent dimensions.")
    _validate_configured_dimensions(identity.vector_dimensions)
    return chunks, vectors, identity


def persist_document_index(document, chunks, vectors, identity, *, generation: int) -> None:
    """Write a complete generation; callers wrap this and the active-pointer update atomically."""
    for index, (content, vector) in enumerate(zip(chunks, vectors, strict=True)):
        chunk = DocumentChunk.objects.create(
            document=document,
            knowledge_base_id=document.knowledge_base_id,
            ingestion_generation=generation,
            chunk_index=index,
            content=content,
            token_estimate=max(1, len(content) // 2),
            metadata={"source": document.title, "content_type": document.content_type},
        )
        EmbeddingRecord.objects.create(
            chunk=chunk,
            vector=[] if should_use_pgvector() else vector,
            **identity.as_record_fields(),
            status=EmbeddingRecord.Status.READY,
            embedded_at=timezone.now(),
        )
        upsert_chunk_vector(chunk, identity, vector)


@observe_stage("embedding")
def embed_texts(texts: list[str]) -> list[list[float]]:
    mode = embedding_mode()
    if mode == "remote":
        api_key = embedding_api_key()
        if not api_key:
            raise EmbeddingSpaceError("Remote embedding credentials are not configured.")
        model = embedding_model()
        base_url = normalized_embedding_base_url()
        configured_dimensions = os.getenv("RAG_EMBEDDING_DIMENSIONS", "").strip()
        if configured_dimensions:
            try:
                _validate_configured_dimensions(int(configured_dimensions))
            except ValueError as exc:
                raise EmbeddingSpaceError("RAG_EMBEDDING_DIMENSIONS must be an integer.") from exc
        # Fail configuration checks before making a billable provider request.
        embedding_space_identity(int(configured_dimensions or "1"), mode=mode, model=model, base_url=base_url)
        try:
            embeddings = OpenAIEmbeddings(
                model=model,
                api_key=api_key,
                base_url=base_url,
            )
            vectors = embeddings.embed_documents(texts)
        except Exception as exc:
            provider = urlparse(base_url).hostname or "unknown-provider"
            logger.warning(
                "rag_embedding_request_failed provider=%s model=%s error_class=%s fallback=denied",
                provider,
                model,
                type(exc).__name__,
            )
            raise EmbeddingRequestError(type(exc).__name__) from exc
    else:
        vectors = [local_embedding(text) for text in texts]
        logger.info(
            "rag_embedding_local_hash_selected model=%s algorithm=%s", LOCAL_EMBEDDING_MODEL, "sha256-token-hash-v1"
        )

    if not vectors or any(not vector or any(not math.isfinite(float(value)) for value in vector) for vector in vectors):
        raise EmbeddingSpaceError("Embedding service returned an empty or non-finite vector.")
    dimensions = len(vectors[0])
    _validate_configured_dimensions(dimensions)
    identity = embedding_space_identity(
        dimensions,
        mode=mode,
        model=embedding_model() if mode == "remote" else LOCAL_EMBEDDING_MODEL,
        base_url=normalized_embedding_base_url() if mode == "remote" else "",
    )
    if identity.normalized:
        vectors = [normalize_vector(vector) for vector in vectors]
    return vectors


def embed_query(query: str) -> list[float]:
    return embed_texts([query])[0]


def use_remote_embeddings() -> bool:
    return embedding_mode() == "remote"


class EmbeddingRequestError(EmbeddingSpaceError):
    def __init__(self, error_class: str):
        self.failure_code = f"embedding_request_failed:{error_class}"
        super().__init__(self.failure_code)


def _validate_configured_dimensions(dimensions: int) -> None:
    configured = os.getenv("RAG_EMBEDDING_DIMENSIONS", "").strip()
    if configured:
        try:
            expected = int(configured)
        except ValueError as exc:
            raise EmbeddingSpaceError("RAG_EMBEDDING_DIMENSIONS must be an integer.") from exc
        if expected != dimensions:
            raise EmbeddingSpaceError(f"Embedding dimension mismatch: configured {expected}, received {dimensions}.")


def embedding_api_key() -> str:
    return (
        os.getenv("BAILIAN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_EMBEDDING_API_KEY") or ""
    ).strip()


def embedding_model() -> str:
    return (
        os.getenv("BAILIAN_EMBEDDING_MODEL") or os.getenv("OPENAI_EMBEDDING_MODEL") or DEFAULT_BAILIAN_EMBEDDING_MODEL
    ).strip()


def normalized_embedding_base_url() -> str:
    base_url = (
        os.getenv("BAILIAN_EMBEDDING_BASE_URL")
        or os.getenv("DASHSCOPE_BASE_URL")
        or os.getenv("OPENAI_EMBEDDING_BASE_URL")
        or DEFAULT_BAILIAN_EMBEDDING_BASE_URL
    )
    if base_url.startswith("https//"):
        return base_url.replace("https//", "https://", 1)
    if base_url.startswith("http//"):
        return base_url.replace("http//", "http://", 1)
    return base_url
