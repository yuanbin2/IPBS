from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from django.db import transaction
from langchain_openai import OpenAIEmbeddings

from .models import Document, DocumentChunk, EmbeddingRecord, KnowledgeBase


DEFAULT_KNOWLEDGE_BASE_NAME = "默认知识库"
DEFAULT_BAILIAN_EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_BAILIAN_EMBEDDING_MODEL = "text-embedding-v1"
LOCAL_EMBEDDING_MODEL = "local-hash-embedding"
LOCAL_EMBEDDING_DIMENSIONS = 384
CHUNK_SIZE = 900
CHUNK_OVERLAP = 140
VECTOR_SCORE_WEIGHT = 0.72
KEYWORD_SCORE_WEIGHT = 0.28


@dataclass(frozen=True)
class SearchResult:
    document_id: int
    document_title: str
    chunk_id: int
    chunk_index: int
    content: str
    score: float


def get_default_knowledge_base() -> KnowledgeBase:
    knowledge_base, _ = KnowledgeBase.objects.get_or_create(
        name=DEFAULT_KNOWLEDGE_BASE_NAME,
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


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@transaction.atomic
def ingest_document(document: Document) -> Document:
    document.status = Document.Status.PROCESSING
    document.error_message = ""
    document.save(update_fields=["status", "error_message", "updated_at"])

    try:
        text = extract_text_from_document(document)
        chunks = split_text(text)
        if not chunks:
            raise ValueError("文档没有可索引的文本内容。")

        document.chunks.all().delete()
        vectors = embed_texts(chunks)

        for index, (content, vector) in enumerate(zip(chunks, vectors)):
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
                model=embedding_model() if use_remote_embeddings() else LOCAL_EMBEDDING_MODEL,
                vector=vector,
                vector_dimensions=len(vector),
            )

        document.status = Document.Status.READY
        document.chunk_count = len(chunks)
        document.save(update_fields=["status", "chunk_count", "updated_at"])
    except Exception as exc:
        document.status = Document.Status.FAILED
        document.error_message = str(exc)
        document.save(update_fields=["status", "error_message", "updated_at"])
    return document


def embed_texts(texts: list[str]) -> list[list[float]]:
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
    return embedding_api_key() != ""


def embedding_api_key() -> str:
    return (
        os.getenv("BAILIAN_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("OPENAI_EMBEDDING_API_KEY")
        or ""
    ).strip()


def embedding_model() -> str:
    return (
        os.getenv("BAILIAN_EMBEDDING_MODEL")
        or os.getenv("OPENAI_EMBEDDING_MODEL")
        or DEFAULT_BAILIAN_EMBEDDING_MODEL
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


def local_embedding(text: str, dimensions: int = LOCAL_EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    tokens = keyword_tokens(text)
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = -1.0 if digest[4] % 2 else 1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    left_values = list(left)
    right_values = list(right)
    if not left_values or not right_values or len(left_values) != len(right_values):
        return 0.0
    numerator = sum(a * b for a, b in zip(left_values, right_values))
    left_norm = math.sqrt(sum(a * a for a in left_values))
    right_norm = math.sqrt(sum(b * b for b in right_values))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def keyword_tokens(text: str) -> list[str]:
    normalized = text.lower()
    english_tokens = re.findall(r"[a-z0-9_]{2,}", normalized)
    chinese_sequences = re.findall(r"[\u4e00-\u9fff]+", normalized)

    tokens: list[str] = [*english_tokens]
    for sequence in chinese_sequences:
        if len(sequence) <= 12:
            tokens.append(sequence)
        tokens.extend(sequence[index : index + 2] for index in range(max(0, len(sequence) - 1)))
        tokens.extend(sequence[index : index + 3] for index in range(max(0, len(sequence) - 2)))

    seen: set[str] = set()
    unique_tokens: list[str] = []
    for token in tokens:
        if token and token not in seen:
            seen.add(token)
            unique_tokens.append(token)
    return unique_tokens


def keyword_similarity(query: str, title: str, content: str) -> float:
    query_terms = keyword_tokens(query)
    if not query_terms:
        return 0.0

    title_lower = title.lower()
    content_lower = content.lower()
    query_lower = query.lower().strip()
    score = 0.0

    if query_lower and query_lower in content_lower:
        score += 0.35
    if query_lower and query_lower in title_lower:
        score += 0.25

    matched_terms = 0
    title_matches = 0
    for term in query_terms:
        if term in content_lower:
            matched_terms += 1
        if term in title_lower:
            title_matches += 1

    score += 0.5 * (matched_terms / len(query_terms))
    score += 0.2 * (title_matches / len(query_terms))
    return min(score, 1.0)


def hybrid_relevance_score(query: str, title: str, content: str, vector_score: float) -> float:
    normalized_vector_score = max(vector_score, 0.0)
    keyword_score = keyword_similarity(query, title, content)
    return (VECTOR_SCORE_WEIGHT * normalized_vector_score) + (KEYWORD_SCORE_WEIGHT * keyword_score)


def search_knowledge_base(query: str, knowledge_base_id: int | None = None, limit: int = 5) -> list[SearchResult]:
    query_vector = embed_query(query)
    records = EmbeddingRecord.objects.select_related("chunk", "chunk__document", "chunk__knowledge_base")
    if knowledge_base_id:
        records = records.filter(chunk__knowledge_base_id=knowledge_base_id)

    scored: list[SearchResult] = []
    for record in records:
        vector_score = cosine_similarity(query_vector, record.vector)
        chunk = record.chunk
        score = hybrid_relevance_score(query, chunk.document.title, chunk.content, vector_score)
        if score <= 0:
            continue
        scored.append(
            SearchResult(
                document_id=chunk.document_id,
                document_title=chunk.document.title,
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                score=score,
            )
        )

    return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]


def format_search_results(results: list[SearchResult]) -> str:
    if not results:
        return "知识库没有检索到高相关片段。"

    lines = []
    for index, result in enumerate(results, start=1):
        lines.append(
            "\n".join(
                [
                    f"[{index}] 文档：{result.document_title}",
                    f"相似度：{result.score:.3f}",
                    f"片段：{result.content}",
                ]
            )
        )
    return "\n\n".join(lines)
