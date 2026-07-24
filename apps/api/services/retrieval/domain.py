# apps/api/services/retrieval/domain.py

"""Shared retrieval value objects."""

from dataclasses import dataclass
from uuid import UUID

RRF_K = 60


@dataclass(frozen=True)
class RankedId:
    """One identifier and its one-based rank in a source list."""

    id: UUID
    rank: int


@dataclass(frozen=True)
class FusedResult:
    """One deterministically fused retrieval result."""

    id: UUID
    score: float
    sources: frozenset[str]


@dataclass(frozen=True)
class RerankItem:
    """Minimal result data exposed to a future reranker."""

    id: UUID
    content: str
    score: float
