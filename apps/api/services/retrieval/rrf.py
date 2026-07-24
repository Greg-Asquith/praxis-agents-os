# apps/api/services/retrieval/rrf.py

"""Pure weighted reciprocal-rank fusion."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from uuid import UUID

from services.retrieval.domain import RRF_K, FusedResult, RankedId


def rrf_merge(
    lists: Mapping[str, Sequence[RankedId]],
    *,
    k: int = RRF_K,
    limit: int,
    weights: Mapping[str, float] | None = None,
) -> list[FusedResult]:
    """Fuse ranked lists with deterministic weighted reciprocal rank."""
    if k < 0:
        raise ValueError("k must be non-negative")
    if limit < 0:
        raise ValueError("limit must be non-negative")

    scores: dict[UUID, float] = defaultdict(float)
    sources: dict[UUID, set[str]] = defaultdict(set)
    for source, ranked_ids in lists.items():
        weight = 1.0 if weights is None else weights.get(source, 1.0)
        if weight < 0:
            raise ValueError("weights must be non-negative")
        for ranked_id in ranked_ids:
            if ranked_id.rank < 1:
                raise ValueError("ranks must be one-based")
            scores[ranked_id.id] += weight / (k + ranked_id.rank)
            sources[ranked_id.id].add(source)

    fused = [
        FusedResult(
            id=result_id,
            score=score,
            sources=frozenset(sources[result_id]),
        )
        for result_id, score in scores.items()
    ]
    fused.sort(key=lambda item: (-item.score, item.id))
    return fused[:limit]
