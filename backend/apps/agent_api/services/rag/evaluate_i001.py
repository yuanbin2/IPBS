"""Frozen, synthetic I-001 retrieval ablation; no production database writes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import time
from decimal import Decimal
from pathlib import Path

from agent.query_rewriting import rewrite_retrieval_query

from .ingest import embed_texts
from .search import (
    KEYWORD_SCORE_WEIGHT,
    RERANK_SCORE_WEIGHT,
    VECTOR_SCORE_WEIGHT,
    SearchResult,
    diversify_search_results,
    expand_multilingual_query,
    hybrid_relevance_score,
    keyword_similarity,
    query_entity_terms,
    rerank_search_results,
)
from .text import cosine_similarity, local_embedding

VARIANTS = (
    "keyword",
    "vector",
    "hybrid",
    "hybrid_rewrite",
    "hybrid_rewrite_rerank",
    "hybrid_rewrite_rerank_0_2",
    "hybrid_rewrite_rerank_0_6",
)


def _local_embed(texts: list[str]) -> list[list[float]]:
    return [local_embedding(text) for text in texts]


def load_frozen_data(corpus_path: Path, questions_path: Path):
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    chunks = corpus["chunks"]
    cases = questions["cases"]
    chunk_ids = [item["id"] for item in chunks]
    case_ids = [item["id"] for item in cases]
    if len(chunk_ids) != len(set(chunk_ids)) or len(case_ids) != len(set(case_ids)):
        raise ValueError("Duplicate corpus or case ID")
    if len(cases) < 30 or {item["split"] for item in cases} != {"tune", "validation"}:
        raise ValueError("Need at least 30 cases and fixed tune/validation splits")
    if not {"chinese_entity", "follow_up", "duplicate", "no_answer"} <= {item["slice"] for item in cases}:
        raise ValueError("Required risk slices are missing")
    for case in cases:
        if not set(case["gold"]) <= set(chunk_ids):
            raise ValueError(f"Unknown gold chunk in {case['id']}")
        if case["slice"] == "no_answer" and case["gold"]:
            raise ValueError(f"No-answer case has gold chunks: {case['id']}")
    return corpus, questions


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (index - low), 3)


def _summarize(rows: list[dict]) -> dict:
    answerable = [row for row in rows if row["gold"]]
    no_answer = [row for row in rows if not row["gold"]]
    hits = sum(bool(set(row["top5"]) & set(row["gold"])) for row in answerable)
    reciprocal_ranks = []
    for row in answerable:
        first = next((index for index, chunk in enumerate(row["top10"], 1) if chunk in row["gold"]), None)
        reciprocal_ranks.append(1 / first if first else 0)
    latencies = [row["latency_ms"] for row in rows]
    return {
        "cases": len(rows),
        "answerable": len(answerable),
        "recall_at_5": round(hits / len(answerable), 4) if answerable else None,
        "recall_hits": hits,
        "mrr_at_10": round(statistics.mean(reciprocal_ranks), 4) if reciprocal_ranks else None,
        "no_answer_with_candidates": sum(bool(row["top5"]) for row in no_answer),
        "no_answer_cases": len(no_answer),
        "p50_ms": _percentile(latencies, 0.5),
        "p95_ms": _percentile(latencies, 0.95),
        "misses": [row["id"] for row in answerable if not set(row["top5"]) & set(row["gold"])],
    }


def _answer_evidence(path: Path | None, case_ids: set[str]) -> dict:
    if path is None:
        return {
            "groundedness": None,
            "groundedness_reviewed_cases": 0,
            "full_request_cost": None,
            "cost_covered_cases": 0,
            "cost_complete": False,
            "currency": None,
            "price_version": None,
            "reason": "answer_generation_not_run",
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload["records"]
    if len({row["case_id"] for row in records}) != len(records):
        raise ValueError("Duplicate answer evidence case ID")
    if not {row["case_id"] for row in records} <= case_ids:
        raise ValueError("Unknown answer evidence case ID")
    reviewed = [row for row in records if row.get("review_status") == "human_reviewed" and row.get("reviewer")]
    grounded = [row["grounded"] for row in reviewed if isinstance(row.get("grounded"), bool)]
    costs = [row.get("model_accounting") for row in records]
    priced = [item for item in costs if item and item.get("complete_cost")]
    price_versions = {item.get("price_version") for item in priced}
    currencies = {item.get("currency") for item in priced}
    complete = (
        {row["case_id"] for row in records} == case_ids
        and len(priced) == len(case_ids)
        and len(price_versions) == 1
        and len(currencies) == 1
    )
    return {
        "groundedness": round(sum(grounded) / len(grounded), 4) if grounded else None,
        "groundedness_reviewed_cases": len(grounded),
        "cost_covered_cases": len(priced),
        "full_request_cost": (str(sum(Decimal(item["known_cost"]) for item in costs)) if complete else None),
        "cost_complete": complete,
        "currency": next(iter(currencies)) if complete else None,
        "price_version": next(iter(price_versions)) if complete else None,
        "reason": None if grounded else "no_human_reviewed_answer_claims",
    }


def evaluate(corpus: dict, questions: dict, *, embedding: str, answer_records: Path | None = None) -> dict:
    if embedding not in {"local_hash", "remote"}:
        raise ValueError("embedding must be local_hash or remote")
    chunks, cases = corpus["chunks"], questions["cases"]
    rewritten = {case["id"]: rewrite_retrieval_query(None, case["question"], case.get("history")) for case in cases}
    base_queries = {case["id"]: expand_multilingual_query(case["question"]) for case in cases}
    rewritten_queries = {case["id"]: expand_multilingual_query(rewritten[case["id"]]) for case in cases}
    if embedding == "remote":
        if not os.getenv("RAG_EMBEDDING_MODEL_VERSION"):
            raise ValueError("Remote embedding needs an explicit RAG_EMBEDDING_MODEL_VERSION")
        if not any(os.getenv(name) for name in ("BAILIAN_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_EMBEDDING_API_KEY")):
            raise ValueError("Remote embedding credentials are unavailable")
        os.environ["RAG_EMBEDDING_MODE"] = "remote"
        embed = embed_texts
    else:
        embed = _local_embed
    indexing_started = time.perf_counter()
    vectors = embed([item["text"] for item in chunks])
    indexing_ms = round((time.perf_counter() - indexing_started) * 1000, 3)
    query_vectors = {}
    query_embedding_ms = {}
    for query in dict.fromkeys([*base_queries.values(), *rewritten_queries.values()]):
        started = time.perf_counter()
        query_vectors[query] = embed([query])[0]
        query_embedding_ms[query] = (time.perf_counter() - started) * 1000
    document_ids = {
        value: index for index, value in enumerate(dict.fromkeys(item["document_id"] for item in chunks), 1)
    }
    rows = []
    for case in cases:
        for variant in VARIANTS:
            use_rewrite = variant.startswith("hybrid_rewrite")
            query = rewritten_queries[case["id"]] if use_rewrite else base_queries[case["id"]]
            started = time.perf_counter()
            scored = []
            for chunk_index, (item, vector) in enumerate(zip(chunks, vectors, strict=True), 1):
                if variant == "keyword":
                    score = keyword_similarity(query, item["title"], item["text"])
                elif variant == "vector":
                    score = max(0.0, cosine_similarity(query_vectors[query], vector))
                else:
                    score = hybrid_relevance_score(
                        query, item["title"], item["text"], cosine_similarity(query_vectors[query], vector)
                    )
                if score > 0:
                    scored.append(
                        SearchResult(
                            document_ids[item["document_id"]], item["title"], chunk_index, 0, item["text"], score
                        )
                    )
            if variant.startswith("hybrid_rewrite_rerank"):
                weight = {"hybrid_rewrite_rerank_0_2": 0.2, "hybrid_rewrite_rerank_0_6": 0.6}.get(
                    variant, RERANK_SCORE_WEIGHT
                )
                scored = rerank_search_results(query, scored, entity_terms=query_entity_terms(query), weight=weight)
            top5 = diversify_search_results(scored, 5)
            top10 = diversify_search_results(scored, 10)
            scoring_ms = (time.perf_counter() - started) * 1000
            rows.append(
                {
                    "id": case["id"],
                    "split": case["split"],
                    "slice": case["slice"],
                    "variant": variant,
                    "gold": case["gold"],
                    "top5": [chunks[result.chunk_id - 1]["id"] for result in top5],
                    "top10": [chunks[result.chunk_id - 1]["id"] for result in top10],
                    "latency_ms": round(scoring_ms + (0 if variant == "keyword" else query_embedding_ms[query]), 3),
                    "query": query,
                }
            )
    summary = {
        split: {
            variant: _summarize([row for row in rows if row["split"] == split and row["variant"] == variant])
            for variant in VARIANTS
        }
        for split in ("tune", "validation")
    }
    answer_evidence = _answer_evidence(answer_records, {case["id"] for case in cases})
    if embedding == "remote" and answer_evidence["cost_complete"]:
        answer_evidence["full_request_cost"] = None
        answer_evidence["cost_complete"] = False
        answer_evidence["reason"] = "remote_embedding_usage_unpriced"
    answer_evidence["cost_scope"] = "configured_model_api_prices_only; infrastructure excluded"
    return {
        "schema_version": 1,
        "annotation_status": questions["annotation_status"],
        "embedding": embedding,
        "indexing_ms": indexing_ms,
        "query_embedding_latency_note": "Measured once per unique query and added to each applicable arm; not a live end-to-end request latency.",
        "weights": {"vector": VECTOR_SCORE_WEIGHT, "keyword": KEYWORD_SCORE_WEIGHT, "rerank": RERANK_SCORE_WEIGHT},
        "summary": summary,
        "answer_evidence": answer_evidence,
        "rows": rows,
    }


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
