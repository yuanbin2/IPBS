"""Versioned evaluation inputs, run provenance, and deterministic aggregation."""

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings

SCORER_VERSION = "evidence-rubric-1.2"
MAX_DATASET_CASES = 160
MAX_BATCH_CASES = 30


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def snapshot_case(case) -> dict:
    annotation = case.annotation if isinstance(case.annotation, dict) else {}
    return {
        "case_key": str(case.case_key),
        "database_case_id": case.pk,
        "question": case.question,
        "workspace_key": case.workspace_key,
        "category": case.category,
        "expected_route": case.expected_route,
        "expected_agent": case.expected_agent,
        "expected_answer": case.expected_answer,
        "reference_keywords": case.reference_keywords,
        "annotation": annotation,
        "annotation_status": annotation.get("review_status", "draft"),
        "source_version": annotation.get("source_version", "unknown"),
    }


def prompt_implementation_hash() -> str:
    project_root = Path(settings.BASE_DIR).parent
    prompt_files = (
        Path("agent/rag_prompts.py"),
        Path("agent/simple_agent.py"),
        Path("agent/specialized_agents.py"),
        Path("agent/multi_agent.py"),
    )
    digest = hashlib.sha256()
    try:
        for relative in prompt_files:
            digest.update(relative.as_posix().encode("utf-8"))
            digest.update((project_root / relative).read_bytes())
    except OSError:
        return "unknown"
    return digest.hexdigest()


def collect_run_provenance(dataset, *, expected_case_count: int) -> dict:
    git_sha = os.getenv("GIT_SHA") or os.getenv("SOURCE_VERSION") or os.getenv("RAILWAY_GIT_COMMIT_SHA") or "unknown"
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "https://poloai.top/v1/").strip()
    provider = urlparse(base_url).hostname or "unknown" if api_key else "unknown"
    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini") if api_key else "unknown"
    prompt_hash = prompt_implementation_hash()
    selected_cases = dataset.snapshot[:expected_case_count]
    annotations_reviewed = all(case.get("annotation_status") == "human_reviewed" for case in selected_cases)
    provenance = {
        "git_sha": git_sha,
        "dataset_version": dataset.version,
        "dataset_hash": dataset.manifest_hash,
        "scorer_version": SCORER_VERSION,
        "model_provider": provider,
        "model_name": model_name,
        "model_parameters": {"temperature": "0 (agent configured)", "other_parameters": "unknown"},
        "prompt_hash": prompt_hash,
        "corpus_version": os.getenv("EVALUATION_CORPUS_VERSION", "unknown"),
        "index_version": os.getenv("RAG_INDEX_VERSION", "unknown"),
        "runtime_config": {
            "settings_module": os.getenv("DJANGO_SETTINGS_MODULE", "unknown"),
            "debug": bool(settings.DEBUG),
            "local_mode": bool(getattr(settings, "LOCAL_MODE", False)),
            "security_enforced": bool(getattr(settings, "AGENT_SECURITY_ENFORCED", False)),
            "corpus_version": os.getenv("EVALUATION_CORPUS_VERSION", "unknown"),
            "index_version": os.getenv("RAG_INDEX_VERSION", "unknown"),
        },
        "expected_case_count": expected_case_count,
        "all_case_annotations_human_reviewed": annotations_reviewed,
    }
    provenance["runtime_config_hash"] = content_hash(provenance["runtime_config"])
    required = (
        "git_sha",
        "dataset_version",
        "dataset_hash",
        "scorer_version",
        "model_provider",
        "model_name",
        "prompt_hash",
        "corpus_version",
        "index_version",
        "runtime_config_hash",
    )
    provenance["unknown_provenance"] = [key for key in required if provenance.get(key) in (None, "unknown", "")]
    provenance["formal_comparable"] = not provenance["unknown_provenance"] and annotations_reviewed
    provenance["comparison_fingerprint"] = content_hash(
        {key: provenance[key] for key in required} | {"annotations_human_reviewed": annotations_reviewed}
    )
    return provenance


def summarize_results(result_records) -> dict:
    """Return deterministic counts; preserve every outcome in its own denominator."""
    statuses = [item["status"] for item in result_records]
    passed = sum(1 for item in result_records if item["status"] == "completed" and item.get("passed"))
    return {
        "total": len(statuses),
        "passed": passed,
        "completed": statuses.count("completed"),
        "needs_review": statuses.count("needs_review"),
        "errors": statuses.count("failed"),
        "skipped": statuses.count("skipped"),
        "pending": statuses.count("pending") + statuses.count("running"),
        "pass_rate_adjudicated": (
            round(passed / statuses.count("completed"), 4) if statuses.count("completed") else None
        ),
    }


def batches_comparable(first: dict, second: dict) -> bool:
    return bool(
        first.get("formal_comparable")
        and second.get("formal_comparable")
        and first.get("comparison_fingerprint")
        and first.get("comparison_fingerprint") == second.get("comparison_fingerprint")
    )
