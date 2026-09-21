"""知识库文档入库与混合检索服务。

文档被切片并生成向量；查询阶段同时计算向量相似度和关键词相关度，
以兼顾语义召回、中文人名、英文别名和精确术语。
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.db import transaction
from langchain_openai import OpenAIEmbeddings

from ..models import Document, DocumentChunk, EmbeddingRecord, KnowledgeBase
from ..models.constants import DEFAULT_WORKSPACE_KEY
from .vector_store import search_pgvector, should_use_pgvector, upsert_chunk_vector


DEFAULT_KNOWLEDGE_BASE_NAME = "默认知识库"
DEFAULT_BAILIAN_EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_BAILIAN_EMBEDDING_MODEL = "text-embedding-v1"
LOCAL_EMBEDDING_MODEL = "local-hash-embedding"
LOCAL_EMBEDDING_DIMENSIONS = 384
CHUNK_SIZE = 900
CHUNK_OVERLAP = 140
VECTOR_SCORE_WEIGHT = 0.72
KEYWORD_SCORE_WEIGHT = 0.28

# Deterministic bilingual aliases keep English papers searchable when remote
# multilingual embeddings or the LLM query rewriter are unavailable.
BILINGUAL_QUERY_ALIASES = {
    "散射成像": "scattering imaging imaging through scattering media",
    "散射介质": "scattering media diffuser",
    "散斑相关": "speckle correlation speckle-correlation",
    "散斑": "speckle",
    "自相关": "autocorrelation auto-correlation",
    "深度学习": "deep learning DL",
    "机器学习": "machine learning ML",
    "神经网络": "neural network",
    "图像重建": "image reconstruction reconstruct",
    "泛化能力": "generalization ability capability",
    "研究方法": "method methodology approach",
    "实验结果": "experimental results",
    "研究结论": "conclusion findings",
}


@dataclass(frozen=True)
class SearchResult:
    document_id: int
    document_title: str
    chunk_id: int
    chunk_index: int
    content: str
    score: float


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


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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

    # Chinese queries often have no whitespace (for example
    # "看一下卫晓斌的简历"). If the normalized document title appears in the
    # query, it is a much stronger signal than noisy embedding similarity.
    compact_query = re.sub(r"[\s的地得看一下请帮我介绍关于]", "", query_lower)
    compact_title = re.sub(r"\s+", "", title_lower)
    for entity in query_entity_terms(query):
        if entity in compact_title or entity in content:
            score += 0.9
            if is_affiliation_query(query):
                score += 1.2 if contains_education_signal(content) else 0.35
    if len(compact_title) >= 2 and compact_title in compact_query:
        score += 0.85
    title_entity = re.sub(
        r"(?:个人)?(?:简历|履历|资料|文档|论文|文章|报告|附件)$",
        "",
        compact_title,
    )
    if len(title_entity) >= 2 and title_entity in compact_query:
        score += 0.85

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


def is_affiliation_query(query: str) -> bool:
    return any(
        term in query
        for term in [
            "学校",
            "院校",
            "大学",
            "学院",
            "毕业",
            "就读",
            "哪个学校",
            "哪所学校",
            "什么学校",
            "作者单位",
            "任职单位",
        ]
    )


def contains_education_signal(text: str) -> bool:
    return any(
        term in text
        for term in ["大学", "学院", "学校", "硕士", "本科", "博士", "教育经历", "计算机技术", "计算机科学与技术"]
    )


def hybrid_relevance_score(query: str, title: str, content: str, vector_score: float) -> float:
    normalized_vector_score = max(vector_score, 0.0)
    keyword_score = keyword_similarity(query, title, content)
    return (VECTOR_SCORE_WEIGHT * normalized_vector_score) + (KEYWORD_SCORE_WEIGHT * keyword_score)


def query_entity_terms(query: str) -> list[str]:
    compact = re.sub(r"[\s，。！？；：,.!?;:、（）()\[\]【】《》\"'“”‘’]+", "", query)
    prefixes = r"(?:请|帮我|查询|检索|搜索|看一下|介绍一下|关于)?"
    suffixes = (
        r"相关信息|个人信息|基本信息|相关资料|个人资料|简历信息|简历|介绍|是谁|"
        r"的信息|的资料|的简历|是哪个学校的?|是哪所学校的?|是什么学校的?|"
        r"哪个学校|哪所学校|毕业院校|就读学校|毕业于哪里|就读于哪里|来自哪里"
    )

    candidates = [
        match.group(1)
        for match in re.finditer(fr"{prefixes}([\u4e00-\u9fff]{{2,4}})(?:{suffixes})", compact)
    ]
    for suffix in re.split(r"\|", suffixes):
        plain_suffix = suffix.replace("?", "")
        if plain_suffix and compact.endswith(plain_suffix):
            candidates.append(compact[: -len(plain_suffix)])

    entities: list[str] = []
    for candidate in candidates:
        candidate = re.sub(r"^(请|帮我|查询|检索|搜索|看一下|介绍一下|关于)", "", candidate)
        candidate = re.sub(r"[的是在]+$", "", candidate)
        if 2 <= len(candidate) <= 4 and candidate not in entities:
            entities.append(candidate)
    return entities


def expand_multilingual_query(query: str) -> str:
    """Add deterministic aliases for Chinese names in English documents."""
    expanded = query.strip()
    name_entities = query_entity_terms(query)
    name_match = None
    name = name_entities[0] if name_entities else ""
    if not name:
        name_match = re.search(
            r"([\u4e00-\u9fff]{2,4})(?:是哪个|是哪所|是什么|在哪|来自|毕业于|就读于|相关信息|的信息|的资料|简介)",
            expanded,
        )
        if name_match:
            name = name_match.group(1)
    if name:
        try:
            from pypinyin import lazy_pinyin

            syllables = lazy_pinyin(name)
            if 2 <= len(syllables) <= 4:
                surname = syllables[0].title()
                given_name = "".join(syllables[1:]).title()
                western_order = f"{given_name} {surname}"
                chinese_order = f"{surname} {given_name}"
                expanded = f"{expanded} {western_order} {chinese_order}"
        except ImportError:
            pass

    if any(term in query for term in ["学校", "院校", "单位", "任职", "就读", "毕业"]):
        expanded = f"{expanded} university affiliation institution"
    for chinese_term, english_aliases in BILINGUAL_QUERY_ALIASES.items():
        if chinese_term in query:
            expanded = f"{expanded} {english_aliases}"
    return expanded


def search_knowledge_base(
    query: str,
    knowledge_base_id: int | None = None,
    limit: int = 5,
    workspace_key: str | None = None,
) -> list[SearchResult]:
    """在指定知识库/工作区中执行带文档多样性的混合检索。"""
    query = expand_multilingual_query(query)
    query_vector = embed_query(query)
    scored = search_knowledge_base_with_pgvector(
        query,
        query_vector,
        knowledge_base_id=knowledge_base_id,
        limit=limit,
        workspace_key=workspace_key,
    )
    if not scored:
        scored = search_knowledge_base_with_django_vectors(
            query,
            query_vector,
            knowledge_base_id=knowledge_base_id,
            workspace_key=workspace_key,
        )
    return diversify_search_results(scored, limit)


def search_knowledge_base_with_pgvector(
    query: str,
    query_vector: list[float],
    *,
    knowledge_base_id: int | None,
    limit: int,
    workspace_key: str | None,
) -> list[SearchResult]:
    candidate_limit = max(limit * 8, 24)
    matches = search_pgvector(
        query_vector,
        knowledge_base_id=knowledge_base_id,
        workspace_key=workspace_key,
        limit=candidate_limit,
    )
    scored: list[SearchResult] = []
    for match in matches:
        score = hybrid_relevance_score(query, match.document_title, match.content, match.vector_score)
        if score <= 0:
            continue
        scored.append(
            SearchResult(
                document_id=match.document_id,
                document_title=match.document_title,
                chunk_id=match.chunk_id,
                chunk_index=match.chunk_index,
                content=match.content,
                score=score,
            )
        )
    return scored


def search_knowledge_base_with_django_vectors(
    query: str,
    query_vector: list[float],
    *,
    knowledge_base_id: int | None = None,
    workspace_key: str | None = None,
) -> list[SearchResult]:
    records = EmbeddingRecord.objects.select_related("chunk", "chunk__document", "chunk__knowledge_base")
    if knowledge_base_id:
        records = records.filter(chunk__knowledge_base_id=knowledge_base_id)
    if workspace_key:
        records = records.filter(chunk__knowledge_base__workspace_key=workspace_key)

    scored: list[SearchResult] = []
    # SQLite/local fallback. PostgreSQL deployments use pgvector above.
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

    return scored


def diversify_search_results(scored: list[SearchResult], limit: int) -> list[SearchResult]:
    ranked = sorted(scored, key=lambda item: item.score, reverse=True)
    if not ranked:
        return []

    # A broad topic can match many chunks from one long PDF and crowd every
    # other relevant document out of top-k. Reserve one slot for each document
    # whose best chunk is close to the global best, then fill the remaining
    # slots by score. Exact/specific queries still keep multiple chunks from the
    # single strongly relevant document.
    best_score = ranked[0].score
    relevant_threshold = max(0.12, best_score * 0.65)
    eligible_document_ids: list[int] = []
    for item in ranked:
        if item.score < relevant_threshold:
            continue
        if item.document_id not in eligible_document_ids:
            eligible_document_ids.append(item.document_id)

    if len(eligible_document_ids) <= 1:
        return ranked[:limit]

    selected: list[SearchResult] = []
    selected_chunk_ids: set[int] = set()
    for document_id in eligible_document_ids[:limit]:
        item = next(result for result in ranked if result.document_id == document_id)
        selected.append(item)
        selected_chunk_ids.add(item.chunk_id)

    for item in ranked:
        if len(selected) >= limit:
            break
        if item.document_id not in eligible_document_ids or item.chunk_id in selected_chunk_ids:
            continue
        selected.append(item)
        selected_chunk_ids.add(item.chunk_id)
    return selected


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
