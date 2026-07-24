# apps/api/services/retrieval/__init__.py

"""Shared retrieval primitives."""

from services.retrieval.domain import FusedResult, RankedId, RerankItem
from services.retrieval.reranker import get_reranker
from services.retrieval.rrf import rrf_merge

__all__ = [
    "FusedResult",
    "RankedId",
    "RerankItem",
    "get_reranker",
    "rrf_merge",
]
