"""Identity and compatibility rules for stored and query embeddings."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

LOCAL_HASH_PROVIDER = "local"
LOCAL_HASH_MODEL = "local-hash-embedding"
LOCAL_HASH_VERSION = "sha256-token-hash-v1"
IDENTITY_FIELDS = (
    "provider",
    "model",
    "model_version",
    "algorithm_version",
    "vector_dimensions",
    "normalized",
    "corpus_version",
    "index_version",
)


class EmbeddingSpaceError(ImproperlyConfigured):
    """Embedding space cannot be identified or used safely."""


@dataclass(frozen=True)
class EmbeddingSpaceIdentity:
    provider: str
    model: str
    model_version: str
    algorithm_version: str
    vector_dimensions: int
    normalized: bool
    corpus_version: str
    index_version: str

    def as_record_fields(self) -> dict:
        return asdict(self)


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def embedding_mode() -> str:
    """Resolve mode without permitting remote-request failure to change modes."""
    configured = os.getenv("RAG_EMBEDDING_MODE", "").strip().lower()
    if configured:
        if configured not in {"remote", "local_hash"}:
            raise EmbeddingSpaceError("RAG_EMBEDDING_MODE must be remote or local_hash.")
        return configured
    if _truthy(os.getenv("AGENT_FORCE_LOCAL_EMBEDDINGS", "")) or getattr(settings, "LOCAL_MODE", False):
        return "local_hash"
    return "remote"


def remote_provider(base_url: str) -> str:
    return (urlparse(base_url).hostname or "unknown-provider").lower()


def embedding_space_identity(
    dimensions: int,
    *,
    mode: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> EmbeddingSpaceIdentity:
    if dimensions <= 0:
        raise EmbeddingSpaceError("Embedding vectors must have a positive dimension.")
    mode = mode or embedding_mode()
    corpus_version = os.getenv("RAG_CORPUS_VERSION", "corpus-v1").strip()
    index_version = os.getenv("RAG_INDEX_VERSION", "index-v1").strip()
    if not corpus_version or not index_version:
        raise EmbeddingSpaceError("RAG_CORPUS_VERSION and RAG_INDEX_VERSION must not be empty.")
    if mode == "local_hash":
        return EmbeddingSpaceIdentity(
            provider=LOCAL_HASH_PROVIDER,
            model=LOCAL_HASH_MODEL,
            model_version=LOCAL_HASH_VERSION,
            algorithm_version=LOCAL_HASH_VERSION,
            vector_dimensions=dimensions,
            normalized=True,
            corpus_version=corpus_version,
            index_version=index_version,
        )
    if mode != "remote":
        raise EmbeddingSpaceError("Unsupported embedding mode.")
    model_version = os.getenv("RAG_EMBEDDING_MODEL_VERSION", "").strip()
    if not model_version:
        raise EmbeddingSpaceError("RAG_EMBEDDING_MODEL_VERSION is required for remote embeddings.")
    base_url = base_url or os.getenv(
        "BAILIAN_EMBEDDING_BASE_URL",
        os.getenv("DASHSCOPE_BASE_URL", os.getenv("OPENAI_EMBEDDING_BASE_URL", "https://api.openai.com/v1")),
    )
    normalized = _truthy(os.getenv("RAG_EMBEDDING_NORMALIZED", "false"))
    model_name = (model or os.getenv("BAILIAN_EMBEDDING_MODEL") or os.getenv("OPENAI_EMBEDDING_MODEL") or "").strip()
    algorithm_version = os.getenv("RAG_EMBEDDING_ALGORITHM_VERSION", "provider-api-v1").strip()
    if not model_name or not algorithm_version:
        raise EmbeddingSpaceError("Remote embedding model and algorithm versions must be configured.")
    return EmbeddingSpaceIdentity(
        provider=remote_provider(base_url),
        model=model_name,
        model_version=model_version,
        algorithm_version=algorithm_version,
        vector_dimensions=dimensions,
        normalized=normalized,
        corpus_version=corpus_version,
        index_version=index_version,
    )


def normalize_vector(vector: list[float]) -> list[float]:
    import math

    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if not norm:
        raise EmbeddingSpaceError("A zero vector cannot be normalized.")
    return [float(value) / norm for value in vector]
