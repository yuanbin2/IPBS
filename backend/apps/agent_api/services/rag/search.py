"""RAG 混合检索：查询扩展、向量+关键词融合打分、多样性重排与邻域扩展。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace

from django.db.models import F, Q

from ...models import DocumentChunk, EmbeddingRecord
from ..embedding_space import embedding_space_identity
from ..vector_store import count_incompatible_embeddings, search_pgvector, should_use_pgvector
from .ingest import embed_query
from .text import cosine_similarity, keyword_tokens

VECTOR_SCORE_WEIGHT = 0.72
KEYWORD_SCORE_WEIGHT = 0.28
# 检索后重排（rerank）：无模型依赖的规则重排，信号为「实体命中 > 标题命中 > 关键词覆盖」。
# 注意：以下四个权重与上面的融合权重同为经验初值，尚无 A/B 评测支撑，
# 待按缺陷表 B-056 的评测方案用 Recall@5/MRR@10 标定后再定稿。
RERANK_SCORE_WEIGHT = 0.4
RERANK_ENTITY_WEIGHT = 0.45
RERANK_TITLE_WEIGHT = 0.35
RERANK_COVERAGE_WEIGHT = 0.2
RERANK_AFFILIATION_WEIGHT = 0.15
logger = logging.getLogger(__name__)
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


def compact_query_text(query: str) -> str:
    """去掉空白与常见填充词，便于判断「文档标题是否出现在问句里」。"""
    return re.sub(r"[\s的地得看一下请帮我介绍关于]", "", query.lower())


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
    compact_query = compact_query_text(query)
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


def rerank_signal(
    query: str,
    title: str,
    content: str,
    entity_terms: list[str] | None = None,
) -> float:
    """重排信号：实体命中 > 标题整体命中 > 关键词覆盖率，归一到 0~1。

    与 ``keyword_similarity`` 的区别：这里只用「是否命中」这类强信号做**排序**，
    不做向量分参与，避免在向量噪声较大时把正确文档压到后面（B-055 的放大器场景）。
    """
    terms = query_entity_terms(query) if entity_terms is None else entity_terms
    title_lower = title.lower()
    content_lower = content.lower()
    compact_query = compact_query_text(query)
    compact_title = re.sub(r"\s+", "", title_lower)

    signal = 0.0
    # 实体（人名/机构名）出现在标题里是最强信号，只在正文里次之。
    if any(entity and entity in compact_title for entity in terms):
        signal += RERANK_ENTITY_WEIGHT
    elif any(entity and entity in content for entity in terms):
        signal += RERANK_ENTITY_WEIGHT * 0.6

    title_entity = re.sub(
        r"(?:个人)?(?:简历|履历|资料|文档|论文|文章|报告|附件)$",
        "",
        compact_title,
    )
    title_hit = (len(compact_title) >= 2 and compact_title in compact_query) or (
        len(title_entity) >= 2 and title_entity in compact_query
    )
    if title_hit:
        signal += RERANK_TITLE_WEIGHT

    query_terms = keyword_tokens(query)
    if query_terms:
        hits = sum(1 for term in query_terms if term in content_lower)
        signal += RERANK_COVERAGE_WEIGHT * (hits / len(query_terms))

    # 「哪个学校/毕业院校」类问题：同一文档内含教育信号的切片应排在最前（Recall@1）。
    if is_affiliation_query(query) and contains_education_signal(content):
        signal += RERANK_AFFILIATION_WEIGHT

    return min(signal, 1.0)


def rerank_search_results(
    query: str,
    results: list[SearchResult],
    *,
    entity_terms: list[str] | None = None,
    weight: float = RERANK_SCORE_WEIGHT,
) -> list[SearchResult]:
    """把召回结果按「融合分 + 重排信号」重新排序并返回新列表（不改动入参）。"""
    if not results:
        return []
    terms = query_entity_terms(query) if entity_terms is None else entity_terms
    reranked = [
        replace(
            item,
            score=(1 - weight) * item.score + weight * rerank_signal(query, item.document_title, item.content, terms),
        )
        for item in results
    ]
    reranked.sort(key=lambda item: item.score, reverse=True)
    return reranked


# 人名/机构名后面常紧跟的谓词与疑问片段。它们一旦被 {2,4} 窗口吸进候选，
# 就会把完整姓名截断（「卫晓斌属于哪个学校」→「晓斌属于」），
# 因此统一在长度判断之前剥离（B-055）。
_ENTITY_PREDICATE_SUFFIX = (
    r"来自|属于|毕业于|就读于|任职于|就职于|工作于|任教于|"
    r"就读|毕业|任职|就职|工作|任教|"
    r"是|在|的|什么|哪"
)
_ENTITY_FILLER_PREFIX = "^(?:请问|请|帮我|帮忙|查询|检索|搜索|看一下|查一下|找一下|介绍一下|关于|想知道|想了解|了解|想问)"
# 姓名与后缀之间允许夹一个谓词：「卫晓斌**毕业于**哪个学校」。不显式允许时，
# {2,4} 窗口只能取到「斌毕业于」这种被截断的片段（B-055）。
_ENTITY_LINK = (
    r"(?:来自|属于|毕业于|就读于|任职于|就职于|工作于|任教于|"
    r"就读|毕业|任职|就职|工作|任教)?"
)
# 称谓夹在姓名与谓词之间的写法：「卫晓斌**同学**来自哪里」。
_ENTITY_TITLE = r"(?:同学|老师|先生|女士|博士|教授|同事)?"


def _normalize_entity_candidate(candidate: str) -> str:
    """剥离填充前缀与尾部谓词，只保留人名/机构名本身。"""
    candidate = re.sub(_ENTITY_FILLER_PREFIX, "", candidate)
    while True:
        trimmed = re.sub(rf"(?:{_ENTITY_PREDICATE_SUFFIX})$", "", candidate)
        if trimmed == candidate:
            break
        candidate = trimmed
    return re.sub(r"[的是在]$", "", candidate)


def query_entity_terms(query: str) -> list[str]:
    compact = re.sub(r"[\s，。！？；：,.!?;:、（）()\[\]【】《》\"'“”‘’]+", "", query)
    # 前缀按“长的放前面”，否则「请问…」会被「请」先吃掉、把人名截成「问卫晓斌」。
    prefixes = r"(?:请问|请|帮我|帮忙|查询|检索|搜索|看一下|查一下|找一下|介绍一下|关于|想知道|想了解|了解|想问)?"
    suffixes = (
        r"相关信息|个人信息|基本信息|相关资料|个人资料|简历信息|简历|介绍|是谁|"
        r"的信息|的资料|的简历|的学校|的大学|的院校|的单位|"
        r"是哪个学校的?|是哪所学校的?|是什么学校的?|是哪个大学的?|是哪所大学的?|"
        r"哪个学校的?|哪所学校的?|什么学校的?|哪个大学的?|哪所大学的?|"
        r"哪个学校|哪所学校|什么学校|哪个大学|哪所大学|哪个院校|哪个学院|"
        r"毕业院校|毕业学校|就读学校|就读院校|工作单位|任职单位|"
        r"毕业于哪里|就读于哪里|来自哪里"
    )

    raw_candidates = [
        match.group(1)
        for match in re.finditer(rf"{prefixes}([\u4e00-\u9fff]{{2,4}}){_ENTITY_TITLE}{_ENTITY_LINK}(?:{suffixes})", compact)
    ]
    for suffix in re.split(r"\|", suffixes):
        plain_suffix = suffix.replace("?", "")
        if plain_suffix and compact.endswith(plain_suffix):
            raw_candidates.append(compact[: -len(plain_suffix)])

    entities: list[str] = []
    for raw in raw_candidates:
        candidate = _normalize_entity_candidate(raw)
        if 2 <= len(candidate) <= 4 and candidate not in entities:
            entities.append(candidate)
    # 完整姓名必须排在截断片段之前：下游 expand_multilingual_query 只用
    # entities[0] 生成拼音别名，「卫晓斌」应优先于「晓斌」。
    entities.sort(key=len, reverse=True)
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
    # 实体从**原始问题**抽取后再用于重排：改写串可能丢掉中文姓名（B-055）。
    entity_terms = query_entity_terms(query)
    query = expand_multilingual_query(query)
    query_vector = embed_query(query)
    identity = embedding_space_identity(len(query_vector))
    skipped = count_incompatible_embeddings(identity, knowledge_base_id=knowledge_base_id, workspace_key=workspace_key)
    if skipped:
        logger.warning(
            "rag_embedding_space_mismatch_skipped count=%s provider=%s model=%s model_version=%s "
            "dimensions=%s workspace=%s knowledge_base_id=%s action=review_or_reindex",
            skipped,
            identity.provider,
            identity.model,
            identity.model_version,
            identity.vector_dimensions,
            workspace_key or "all-authorized-workspaces",
            knowledge_base_id or "all",
        )
    scored = search_knowledge_base_with_pgvector(
        query,
        query_vector,
        identity=identity,
        knowledge_base_id=knowledge_base_id,
        limit=limit,
        workspace_key=workspace_key,
    )
    # PostgreSQL is the authoritative vector store when selected. Falling
    # through to EmbeddingRecord JSON there can silently hide pgvector errors
    # or make an empty PostgreSQL result look like a successful local search.
    if not scored and not should_use_pgvector():
        scored = search_knowledge_base_with_django_vectors(
            query,
            query_vector,
            identity=identity,
            knowledge_base_id=knowledge_base_id,
            workspace_key=workspace_key,
        )
    # 排序链路：向量召回 → 混合打分 → 规则重排 → 文档多样性配额。
    scored = rerank_search_results(query, scored, entity_terms=entity_terms)
    return diversify_search_results(scored, limit)


def search_knowledge_base_with_pgvector(
    query: str,
    query_vector: list[float],
    *,
    identity,
    knowledge_base_id: int | None,
    limit: int,
    workspace_key: str | None,
) -> list[SearchResult]:
    candidate_limit = max(limit * 8, 24)
    matches = search_pgvector(
        query_vector,
        identity=identity,
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
    identity,
    knowledge_base_id: int | None = None,
    workspace_key: str | None = None,
) -> list[SearchResult]:
    records = EmbeddingRecord.objects.select_related("chunk", "chunk__document", "chunk__knowledge_base")
    if knowledge_base_id:
        records = records.filter(chunk__knowledge_base_id=knowledge_base_id)
    if workspace_key:
        records = records.filter(chunk__knowledge_base__workspace_key=workspace_key)
    records = records.filter(
        status="ready",
        chunk__ingestion_generation=F("chunk__document__active_ingestion_generation"),
        **identity.as_record_fields(),
    )

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


def expand_search_results_with_neighbors(
    results: list[SearchResult],
    *,
    neighbor_window: int = 1,
    max_results: int = 15,
) -> list[SearchResult]:
    """Attach adjacent chunks while retaining every original semantic hit.

    Vector search treats chunks as independent records.  Agents need a small
    parent-document window as well, otherwise a sentence at a chunk boundary
    loses the explanation immediately before or after it.  Original matches
    are always retained; neighbor chunks fill the remaining budget and the
    final result is ordered by document and ``chunk_index`` for coherent
    reading.
    """
    if not results or max_results <= 0:
        return []

    unique_results: list[SearchResult] = []
    seen_chunk_ids: set[int] = set()
    for result in results:
        if result.chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(result.chunk_id)
        unique_results.append(result)
        if len(unique_results) >= max_results:
            break

    if neighbor_window <= 0:
        return unique_results

    target_indexes: dict[int, set[int]] = {}
    document_rank: dict[int, int] = {}
    for rank, result in enumerate(unique_results):
        document_rank.setdefault(result.document_id, rank)
        indexes = target_indexes.setdefault(result.document_id, set())
        start = max(0, result.chunk_index - neighbor_window)
        indexes.update(range(start, result.chunk_index + neighbor_window + 1))

    chunk_filter = Q()
    for document_id, indexes in target_indexes.items():
        chunk_filter |= Q(document_id=document_id, chunk_index__in=indexes)

    chunks = list(
        DocumentChunk.objects.select_related("document")
        .filter(
            chunk_filter,
            ingestion_generation=F("document__active_ingestion_generation"),
        )
        .order_by("document_id", "chunk_index")
    )
    original_by_id = {result.chunk_id: result for result in unique_results}
    original_by_document: dict[int, list[SearchResult]] = {}
    for result in unique_results:
        original_by_document.setdefault(result.document_id, []).append(result)

    neighbor_candidates: list[tuple[int, int, DocumentChunk, float]] = []
    for chunk in chunks:
        if chunk.id in original_by_id:
            continue
        matches = original_by_document.get(chunk.document_id, [])
        if not matches:
            continue
        nearest = min(matches, key=lambda item: abs(item.chunk_index - chunk.chunk_index))
        distance = abs(nearest.chunk_index - chunk.chunk_index)
        neighbor_candidates.append(
            (
                distance,
                document_rank[chunk.document_id],
                chunk,
                nearest.score * (0.97**distance),
            )
        )

    selected = list(unique_results)
    for _, _, chunk, score in sorted(
        neighbor_candidates,
        key=lambda item: (item[0], item[1], item[2].chunk_index),
    ):
        if len(selected) >= max_results:
            break
        selected.append(
            SearchResult(
                document_id=chunk.document_id,
                document_title=chunk.document.title,
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                score=score,
            )
        )

    return sorted(
        selected,
        key=lambda item: (document_rank.get(item.document_id, len(document_rank)), item.chunk_index),
    )


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
