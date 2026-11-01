"""Run I-001 on a synthetic frozen snapshot; does not write the application DB.

Example:
  .venv/Scripts/python backend/scripts/evaluate_rag_i001.py --embedding local_hash --output docs/evaluation/i001-local-hash-v1.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("BLOG_LOCAL_MODE", "1")

import django  # noqa: E402

django.setup()

from apps.agent_api.services.rag.evaluate_i001 import evaluate, file_sha256, load_frozen_data  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embedding", choices=("local_hash", "remote"), required=True)
    parser.add_argument("--allow-remote", action="store_true", help="Authorize external embedding API requests")
    parser.add_argument("--answer-records", type=Path, help="Optional exported I-005 runs and human answer reviews")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.embedding == "remote" and not args.allow_remote:
        parser.error("remote embedding requires --allow-remote")
    data_dir = BACKEND / "apps" / "agent_api" / "eval_data"
    corpus_path = data_dir / "i001_corpus_v1.json"
    questions_path = data_dir / "i001_questions_v1.json"
    corpus, questions = load_frozen_data(corpus_path, questions_path)
    result = evaluate(corpus, questions, embedding=args.embedding, answer_records=args.answer_records)
    result["provenance"] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "corpus_version": corpus["corpus_version"],
        "corpus_sha256": file_sha256(corpus_path),
        "questions_version": questions["dataset_version"],
        "questions_sha256": file_sha256(questions_path),
        "evaluator_code_sha256": file_sha256(BACKEND / "apps" / "agent_api" / "services" / "rag" / "evaluate_i001.py"),
        "search_code_sha256": file_sha256(BACKEND / "apps" / "agent_api" / "services" / "rag" / "search.py"),
        "rewrite_code_sha256": file_sha256(BACKEND / "agent" / "query_rewriting.py"),
        "retrieval_prompt_sha256": file_sha256(BACKEND / "agent" / "rag_prompts.py"),
        "embedding_model": (
            os.getenv("BAILIAN_EMBEDDING_MODEL") or os.getenv("OPENAI_EMBEDDING_MODEL") or "remote-model-unspecified"
            if args.embedding == "remote"
            else "local-hash-embedding"
        ),
        "embedding_model_version": (
            os.getenv("RAG_EMBEDDING_MODEL_VERSION") if args.embedding == "remote" else "sha256-token-hash-v1"
        ),
        "answer_model": "not_run" if args.answer_records is None else "see_answer_records",
        "answer_prompt": "not_run" if args.answer_records is None else "see_answer_records",
        "top_k": [5, 10],
        "snapshot_backend": "in_memory_exact_vectors",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "summary": result["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
