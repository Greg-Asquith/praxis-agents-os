# apps/api/services/retrieval/reranker.py

"""Optional retrieval reranker contract."""

from collections.abc import Sequence
from typing import Protocol

from core.settings import settings
from services.retrieval.domain import RerankItem


class Reranker(Protocol):
    """Reorder already-fused results without expanding the candidate set."""

    async def rerank(
        self,
        query: str,
        results: Sequence[RerankItem],
    ) -> list[RerankItem]: ...


def get_reranker() -> Reranker | None:
    """Return the configured reranker; the initial engine intentionally has none."""
    if settings.KB_RERANKER == "none":
        return None
    raise ValueError(f"Unsupported knowledge-base reranker: {settings.KB_RERANKER}")
