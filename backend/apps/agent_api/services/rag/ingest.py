"""RAG 入库管线：文本抽取、切分、embedding 与原子化写库。"""

from __future__ import annotations

import os
import re
from pathlib import Path

from django.conf import settings
from django.db import transaction
from langchain_openai import OpenAIEmbeddings

from ...models import Document, DocumentChunk, EmbeddingRecord, KnowledgeBase
from ...models.constants import DEFAULT_WORKSPACE_KEY
from ..vector_store import should_use_pgvector, upsert_chunk_vector
from .text import local_embedding, normalize_text

DEFAULT_KNOWLEDGE_BASE_NAME = "默认知识库"
DEFAULT_BAILIAN_EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_BAILIAN_EMBEDDING_MODEL = "text-embedding-v1"
LOCAL_EMBEDDING_MODEL = "local-hash-embedding"
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


@transaction.atomic
def ingest_document(document: Document) -> Document:
    """原子化完成抽取、切片和向量写入，保证文档状态与索引一致。"""
    document.status = Document.Status.PROCESSING
    document.error_message = ""
    document.save(update_fields=["status", "error_message", "updated_at"])

    try:
        text = extract_text_from_document(document)
        chunks = split_text(text)
        if not chunks:
            raise ValueError("文档没有可索引的文本内容。")

        # 重建前先清除旧切片；整个函数位于事务中，失败时数据库改动会回滚。
        document.chunks.all().delete()
        vectors = embed_texts(chunks)
        model_name = embedding_model() if use_remote_embeddings() else LOCAL_EMBEDDING_MODEL

        for index, (content, vector) in enumerate(zip(chunks, vectors, strict=True)):
            chunk = DocumentChunk.objects.create(
                document=document,
                knowledge_base=document.knowledge_base,
                chunk_index=index,
                content=content,
                token_estimate=max(1, len(content) // 2),
                metadata={
                    "source": document.title,
                    "content_type": document.content_type,
                },
            )
            EmbeddingRecord.objects.create(
                chunk=chunk,
                model=model_name,
                vector=[] if should_use_pgvector() else vector,
                vector_dimensions=len(vector),
            )
            upsert_chunk_vector(chunk, model_name, vector)

        document.status = Document.Status.READY
        document.chunk_count = len(chunks)
        document.save(update_fields=["status", "chunk_count", "updated_at"])
    except Exception as exc:
        document.status = Document.Status.FAILED
        document.error_message = str(exc)
        document.save(update_fields=["status", "error_message", "updated_at"])
    return document


def embed_texts(texts: list[str]) -> list[list[float]]:
    # 远程 embedding 不可用时回退到确定性的本地向量，使开发、测试和
    # 无外网环境仍能完成整条 RAG 流程。
    if use_remote_embeddings():
        try:
            embeddings = OpenAIEmbeddings(
                model=embedding_model(),
                api_key=embedding_api_key(),
                base_url=normalized_embedding_base_url(),
            )
            return embeddings.embed_documents(texts)
        except Exception:
            return [local_embedding(text) for text in texts]
    return [local_embedding(text) for text in texts]


def embed_query(query: str) -> list[float]:
    return embed_texts([query])[0]


def use_remote_embeddings() -> bool:
    if os.getenv("AGENT_FORCE_LOCAL_EMBEDDINGS", "").lower() in {"1", "true", "yes"}:
        return False
    if settings.DEBUG and os.getenv("AGENT_ENABLE_REMOTE_EMBEDDINGS", "").lower() not in {
        "1",
        "true",
        "yes",
    }:
        return False
    return embedding_api_key() != ""


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
