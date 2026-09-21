"""Backward-compatible import surface for the RAG service.

New code should import from apps.agent_api.services.rag. This module keeps older
views and agents on the same pgvector-backed implementation.
"""

from .services.rag import *  # noqa: F401,F403
