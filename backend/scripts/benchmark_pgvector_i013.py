"""I-013: benchmark the real PostgreSQL/pgvector retrieval path.

Run only against a newly migrated, disposable database named blog_i013_bench_*.
The script never reads DATABASE_URL as its input: the operator must explicitly
set I013_BENCH_DATABASE_URL. No private document text is written to the report.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import platform
import random
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

FIXTURE_VERSION = "i013-synthetic-v1"
DEFAULT_SIZES = (1000, 10000)
DEFAULT_CONCURRENCY = (1, 4, 8)
MIN_DB_PREFIX = "blog_i013_bench_"


def validate_database_url(value: str) -> str:
    """Return the safe database name; never include credentials in errors."""
    parsed = urlparse(value)
    name = unquote(parsed.path.lstrip("/"))
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise ValueError("I013_BENCH_DATABASE_URL must use PostgreSQL")
    if parsed.hostname not in {"localhost", "127.0.0.1", "postgres"}:
        raise ValueError("I-013 benchmark accepts only a local or CI PostgreSQL host")
    if not name.startswith(MIN_DB_PREFIX) or len(name) <= len(MIN_DB_PREFIX):
        raise ValueError(f"I-013 benchmark database name must start with {MIN_DB_PREFIX}")
    if not all(ch.isascii() and (ch.isalnum() or ch == "_") for ch in name):
        raise ValueError("I-013 benchmark database name contains unsupported characters")
    return name


def parse_positive_list(value: str) -> tuple[int, ...]:
    try:
        numbers = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise ValueError("expected comma-separated positive integers") from exc
    if not numbers or any(number <= 0 for number in numbers):
        raise ValueError("expected comma-separated positive integers")
    return numbers


def percentile(values: list[float], percent: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percent / 100
    lower, upper = math.floor(rank), math.ceil(rank)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def fixture_vector(index: int, dimensions: int, seed: int) -> list[float]:
    rng = random.Random(seed + index * 1000003)
    values = [rng.uniform(-1.0, 1.0) for _ in range(dimensions)]
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values]


def physical_memory_bytes() -> int | None:
    if sys.platform == "win32":

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        return status.total_physical if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else None
    if hasattr(os, "sysconf"):
        try:
            return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError):
            pass
    return None


def _database_stats(connection) -> dict:
    with connection.cursor() as cursor:
        cursor.execute("""SELECT xact_commit, xact_rollback, blks_read, blks_hit,
                      tup_returned, tup_fetched, temp_bytes,
                      pg_database_size(current_database())
               FROM pg_stat_database WHERE datname = current_database()""")
        row = cursor.fetchone()
    return dict(
        zip(
            (
                "commits",
                "rollbacks",
                "blocks_read",
                "blocks_hit",
                "tuples_returned",
                "tuples_fetched",
                "temp_bytes",
                "database_bytes",
            ),
            map(int, row),
            strict=True,
        )
    )


def _server_info(connection) -> dict:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_setting('server_version'), version()")
        database, server_version, version = cursor.fetchone()
        cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        extension = cursor.fetchone()
        cursor.execute("SHOW shared_buffers")
        shared_buffers = cursor.fetchone()[0]
        cursor.execute("SHOW work_mem")
        work_mem = cursor.fetchone()[0]
        cursor.execute("SHOW max_connections")
        max_connections = cursor.fetchone()[0]
        cursor.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() "
            "AND tablename = 'agent_api_vectorindex' ORDER BY indexname"
        )
        indexes = [row[0] for row in cursor.fetchall()]
    if not extension:
        raise RuntimeError("pgvector extension is missing; apply migrations in the isolated database")
    return {
        "database": database,
        "postgres_version": server_version,
        "server_build": version,
        "pgvector_version": extension[0],
        "shared_buffers": shared_buffers,
        "work_mem": work_mem,
        "max_connections": int(max_connections),
        "vector_indexes": indexes,
    }


def _assert_empty_isolated_db(connection, KnowledgeBase, Document, DocumentChunk) -> None:
    if connection.vendor != "postgresql":
        raise RuntimeError("I-013 requires real PostgreSQL; SQLite results are forbidden")
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('agent_api_vectorindex')")
        if not cursor.fetchone()[0]:
            raise RuntimeError("pgvector table missing; migrate the isolated database first")
        cursor.execute("SELECT EXISTS (SELECT 1 FROM agent_api_vectorindex LIMIT 1)")
        vectors_exist = cursor.fetchone()[0]
    if vectors_exist or KnowledgeBase.objects.exists() or Document.objects.exists() or DocumentChunk.objects.exists():
        raise RuntimeError("I-013 requires an empty, newly migrated isolated database")


def _insert_fixture(
    start: int, end: int, *, seed: int, dimensions: int, knowledge_base, identity, Document, DocumentChunk, connection
) -> None:
    from apps.agent_api.services.vector_store import vector_literal

    workspace_key = knowledge_base.workspace_key
    for first in range(start, end, 100):
        last = min(first + 100, end)
        documents = Document.objects.bulk_create(
            [
                Document(
                    knowledge_base=knowledge_base,
                    workspace_key=workspace_key,
                    title=f"I013 document {index:06d}",
                    status=Document.Status.READY,
                    chunk_count=1,
                )
                for index in range(first, last)
            ]
        )
        chunks = DocumentChunk.objects.bulk_create(
            [
                DocumentChunk(
                    document=doc,
                    knowledge_base=knowledge_base,
                    chunk_index=0,
                    content=f"I013 synthetic marker {index:06d}; deterministic benchmark content.",
                )
                for index, doc in zip(range(first, last), documents, strict=True)
            ]
        )
        placeholders = (
            "(" + ",".join(["%s"] * 4) + ",%s::vector,%s,%s,%s::jsonb," + "now(),%s,%s,%s,%s,%s,%s,'ready','',now())"
        )
        rows = []
        for index, doc, chunk in zip(range(first, last), documents, chunks, strict=True):
            rows.extend(
                (
                    chunk.pk,
                    doc.pk,
                    knowledge_base.pk,
                    workspace_key,
                    vector_literal(fixture_vector(index, dimensions, seed)),
                    identity.model,
                    dimensions,
                    "{}",
                    identity.provider,
                    identity.model_version,
                    identity.algorithm_version,
                    identity.normalized,
                    identity.corpus_version,
                    identity.index_version,
                )
            )
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO agent_api_vectorindex "
                "(chunk_id,document_id,knowledge_base_id,workspace_key,embedding,model,"
                "vector_dimensions,metadata,updated_at,provider,model_version,algorithm_version,"
                "normalized,corpus_version,index_version,status,fallback_reason,embedded_at) VALUES "
                + ",".join([placeholders] * (last - first)),
                rows,
            )


def _request_retrieval(query: str, vector: list[float], identity, knowledge_base_id: int, workspace_key: str) -> list:
    from apps.agent_api.services.rag.search import (
        diversify_search_results,
        rerank_search_results,
        search_knowledge_base_with_pgvector,
    )
    from apps.agent_api.services.vector_store import count_incompatible_embeddings

    count_incompatible_embeddings(identity, knowledge_base_id=knowledge_base_id, workspace_key=workspace_key)
    scored = search_knowledge_base_with_pgvector(
        query,
        vector,
        identity=identity,
        knowledge_base_id=knowledge_base_id,
        limit=5,
        workspace_key=workspace_key,
    )
    return diversify_search_results(rerank_search_results(query, scored), 5)


def _sample_sql_and_plans(
    connection, query: str, vector: list[float], identity, knowledge_base_id: int, workspace_key: str
) -> dict:
    captured = []

    def wrapper(execute, sql, params, many, context):
        if sql.lstrip().upper().startswith("SELECT"):
            kind = "compatibility_count" if "COUNT(*)" in sql.upper() else "vector_search"
            captured.append((kind, sql, params))
        return execute(sql, params, many, context)

    with connection.execute_wrapper(wrapper):
        _request_retrieval(query, vector, identity, knowledge_base_id, workspace_key)
    counts = Counter(kind for kind, _, _ in captured)
    plans = {}
    for kind, sql, params in captured:
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params)
            value = cursor.fetchone()[0]
        plan = value[0] if isinstance(value, list) else json.loads(value)[0]
        plans[kind] = _summarize_plan(plan)
    return {
        "query_count": len(captured),
        "query_kinds": dict(counts),
        "repeated_query_kinds": [kind for kind, count in counts.items() if count > 1],
        "plans": plans,
    }


def _summarize_plan(plan: dict) -> dict:
    nodes = []

    def visit(node):
        nodes.append(
            {
                key: node[key]
                for key in (
                    "Node Type",
                    "Relation Name",
                    "Index Name",
                    "Actual Rows",
                    "Actual Loops",
                    "Actual Total Time",
                    "Shared Hit Blocks",
                    "Shared Read Blocks",
                    "Temp Read Blocks",
                    "Temp Written Blocks",
                )
                if key in node
            }
        )
        for child in node.get("Plans", []):
            visit(child)

    visit(plan["Plan"])
    return {"planning_ms": plan.get("Planning Time"), "execution_ms": plan.get("Execution Time"), "nodes": nodes}


def _scenario(
    *,
    size: int,
    concurrency: int,
    samples: int,
    warmup: int,
    seed: int,
    dimensions: int,
    identity,
    knowledge_base_id: int,
    workspace_key: str,
    targets: list[tuple[int, int]],
) -> dict:
    from django.db import close_old_connections, connection

    from apps.agent_api.services.vector_store import search_pgvector

    def one(position: int, stage: str):
        close_old_connections()
        index, expected_chunk_id = targets[position % len(targets)]
        vector = fixture_vector(index, dimensions, seed)
        query = f"I013 synthetic marker {index:06d}"
        started = time.perf_counter()
        try:
            if stage == "vector":
                found = search_pgvector(
                    vector, identity=identity, knowledge_base_id=knowledge_base_id, workspace_key=workspace_key, limit=5
                )
            else:
                found = _request_retrieval(query, vector, identity, knowledge_base_id, workspace_key)
            elapsed_ms = (time.perf_counter() - started) * 1000
            ids = [item.chunk_id for item in found]
            return elapsed_ms, expected_chunk_id in ids, ids[:1] == [expected_chunk_id], None
        except Exception as exc:  # report only the type, never SQL parameters or content
            return (time.perf_counter() - started) * 1000, False, False, type(exc).__name__

    measurements = {}
    for stage in ("vector", "retrieval"):
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            list(executor.map(lambda i, current_stage=stage: one(i, current_stage), range(warmup)))
            before = _database_stats(connection)
            wall_start = time.perf_counter()
            results = list(executor.map(lambda i, current_stage=stage: one(i, current_stage), range(samples)))
            wall_ms = (time.perf_counter() - wall_start) * 1000
            after = _database_stats(connection)
        errors = Counter(item[3] for item in results if item[3])
        ok = [item for item in results if item[3] is None]
        latencies = [item[0] for item in ok]
        measurements[stage] = {
            "samples": samples,
            "successful": len(ok),
            "errors": dict(errors),
            "error_rate": (samples - len(ok)) / samples,
            "p50_ms": percentile(latencies, 50) if latencies else None,
            "p95_ms": percentile(latencies, 95) if latencies else None,
            "wall_ms": wall_ms,
            "target_recall_at_5": sum(item[1] for item in ok) / len(ok) if ok else None,
            "target_top1": sum(item[2] for item in ok) / len(ok) if ok else None,
            "db_delta": {key: after[key] - before[key] for key in before},
        }
    close_old_connections()
    return {"size": size, "concurrency": concurrency, "measurements": measurements}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default=",".join(map(str, DEFAULT_SIZES)))
    parser.add_argument("--concurrency", default=",".join(map(str, DEFAULT_CONCURRENCY)))
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--seed", type=int, default=13013)
    parser.add_argument("--dimensions", type=int, choices=(384, 1536, 3072), default=384)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        sizes = tuple(sorted(set(parse_positive_list(args.sizes))))
        concurrency = parse_positive_list(args.concurrency)
        if args.samples < 20 or args.warmup < 0:
            raise ValueError("samples must be >= 20 and warmup must be >= 0")
        url = os.environ.get("I013_BENCH_DATABASE_URL", "")
        database_name = validate_database_url(url)
    except ValueError as exc:
        parser.error(str(exc))

    backend_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_root))
    os.environ["DATABASE_URL"] = url
    os.environ["BLOG_LOCAL_MODE"] = "false"
    os.environ["RAG_VECTOR_BACKEND"] = "pgvector"
    os.environ["RAG_EMBEDDING_MODE"] = "local_hash"
    os.environ["AGENT_FORCE_LOCAL_EMBEDDINGS"] = "true"
    os.environ["DJANGO_DEBUG"] = "false"
    os.environ["AGENT_SECURITY_ENFORCED"] = "true"
    os.environ["DJANGO_HTTPS_TERMINATED"] = "true"
    os.environ["DJANGO_SECURE_SSL_REDIRECT"] = "true"
    os.environ["BLOG_MEDIA_STORAGE"] = "file"
    os.environ["DJANGO_SECRET_KEY"] = "isolated-i013-benchmark-key-0123456789-0123456789-0123456789"
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

    import django

    django.setup()
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    from apps.agent_api.models import Document, DocumentChunk, KnowledgeBase
    from apps.agent_api.services.embedding_space import EmbeddingSpaceIdentity

    if connection.settings_dict["NAME"] != database_name:
        raise RuntimeError("resolved Django database differs from I013_BENCH_DATABASE_URL")
    if connection.vendor != "postgresql":
        raise RuntimeError("I-013 requires real PostgreSQL; SQLite results are forbidden")
    migrations = MigrationExecutor(connection)
    if migrations.migration_plan(migrations.loader.graph.leaf_nodes()):
        raise RuntimeError("pending migrations; migrate the isolated database first")
    _assert_empty_isolated_db(connection, KnowledgeBase, Document, DocumentChunk)
    server = _server_info(connection)
    if not any("hnsw" in name and str(args.dimensions) in name for name in server["vector_indexes"]):
        raise RuntimeError("required dimension-specific HNSW index is missing")
    identity = EmbeddingSpaceIdentity(
        provider="i013-fixture",
        model="deterministic-random",
        model_version=FIXTURE_VERSION,
        algorithm_version="python-random-v1",
        vector_dimensions=args.dimensions,
        normalized=True,
        corpus_version=FIXTURE_VERSION,
        index_version=FIXTURE_VERSION,
    )
    workspace_key = "i013-benchmark"
    kb = KnowledgeBase.objects.create(name="I013 synthetic benchmark", workspace_key=workspace_key)
    report = {
        "status": "running",
        "fixture_version": FIXTURE_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "hardware": {
            "system": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
            "physical_memory_bytes": physical_memory_bytes(),
        },
        "database": server,
        "conditions": {
            "sizes": sizes,
            "concurrency": concurrency,
            "samples_per_stage": args.samples,
            "warmup_per_stage": args.warmup,
            "seed": args.seed,
            "dimensions": args.dimensions,
            "limit": 5,
            "embedding": "precomputed synthetic vector",
            "cache": "existing PostgreSQL buffer cache; no reset",
            "request_scope": "vector and retrieval stages exclude embedding/model/network",
        },
        "diagnostic_targets": {
            "error_rate_max": 0,
            "synthetic_target_recall_at_5_min": 0.99,
            "retrieval_select_count_max": 2,
            "retrieval_p95_ms_at_10000_concurrency_1_max": 250,
            "retrieval_p95_ms_at_10000_concurrency_8_max": 750,
        },
        "scenarios": [],
    }
    previous = 0
    try:
        for size in sizes:
            _insert_fixture(
                previous,
                size,
                seed=args.seed,
                dimensions=args.dimensions,
                knowledge_base=kb,
                identity=identity,
                Document=Document,
                DocumentChunk=DocumentChunk,
                connection=connection,
            )
            previous = size
            with connection.cursor() as cursor:
                cursor.execute("ANALYZE agent_api_vectorindex")
                cursor.execute("ANALYZE agent_api_document")
                cursor.execute("ANALYZE agent_api_documentchunk")
                cursor.execute(
                    "SELECT c.id FROM agent_api_documentchunk c "
                    "JOIN agent_api_document d ON d.id = c.document_id "
                    "WHERE d.knowledge_base_id = %s ORDER BY c.id",
                    [kb.pk],
                )
                all_chunks = cursor.fetchall()
                cursor.execute("SELECT COUNT(*) FROM agent_api_vectorindex WHERE knowledge_base_id = %s", [kb.pk])
                vector_count = cursor.fetchone()[0]
            if len(all_chunks) != size or vector_count != size:
                raise RuntimeError("fixture row count differs from the requested size")
            targets = [(index, all_chunks[index][0]) for index in sorted({size // 10, size // 2, size * 9 // 10})]
            probe_index, _ = targets[0]
            query = f"I013 synthetic marker {probe_index:06d}"
            plan = _sample_sql_and_plans(
                connection,
                query,
                fixture_vector(probe_index, args.dimensions, args.seed),
                identity,
                kb.pk,
                workspace_key,
            )
            for workers in concurrency:
                scenario = _scenario(
                    size=size,
                    concurrency=workers,
                    samples=args.samples,
                    warmup=args.warmup,
                    seed=args.seed,
                    dimensions=args.dimensions,
                    identity=identity,
                    knowledge_base_id=kb.pk,
                    workspace_key=workspace_key,
                    targets=targets,
                )
                scenario["sql_probe"] = plan
                report["scenarios"].append(scenario)
                print(
                    f"size={size} concurrency={workers} retrieval_p95_ms="
                    f"{scenario['measurements']['retrieval']['p95_ms']}",
                    flush=True,
                )
        failures = []
        for scenario in report["scenarios"]:
            size, workers = scenario["size"], scenario["concurrency"]
            if scenario["sql_probe"]["query_count"] > 2:
                failures.append((size, workers, "duplicate_sql"))
            for stage, measurement in scenario["measurements"].items():
                if measurement["error_rate"] > 0 or (measurement["target_recall_at_5"] or 0) < 0.99:
                    failures.append((size, workers, stage))
            if size == 10000 and workers in (1, 8):
                limit = 250 if workers == 1 else 750
                latency = scenario["measurements"]["retrieval"]["p95_ms"]
                if latency is None or latency > limit:
                    failures.append((size, workers, "retrieval_p95"))
        report["status"] = "failed_targets" if failures else "completed"
        report["failed_scenarios"] = failures
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 2 if report["status"] != "completed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
