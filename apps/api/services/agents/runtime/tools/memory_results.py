# apps/api/services/agents/runtime/tools/memory_results.py

"""Bounded model-visible memory-search results."""

import json
from typing import Any

from pydantic import BaseModel

from services.agents.runtime.entity_references.domain import MemoryReference

_TRUNCATION_MARKER = "\n\n[Memory content truncated; search again with narrower terms.]"
_NEXT_STEP = "Search again with narrower terms when you need omitted or shortened matches."


class MemorySearchItem(BaseModel):
    """One bounded memory-search hit."""

    id: str
    reference: MemoryReference
    scope: str
    kind: str
    memory_type: str
    title: str
    content: str
    content_truncated: bool
    source: str
    created_by: str
    created_by_user_id: str | None
    effective_confidence: float
    score: float


class SearchMemoryOutput(BaseModel):
    """Bounded memory-search response and continuation guidance."""

    query: str
    results: list[MemorySearchItem]
    total: int
    matches_found: int
    results_truncated: bool
    used_lexical_fallback: bool
    next_step: str


def build_bounded_search_output(
    *,
    query: str,
    hits: list[dict[str, Any]],
    used_lexical_fallback: bool,
    max_chars: int,
) -> dict[str, Any]:
    """Return the highest-ranked hits within an exact serialized-size budget."""
    response: dict[str, Any] = {
        "query": query,
        "results": [],
        "total": 0,
        "matches_found": len(hits),
        "results_truncated": False,
        "used_lexical_fallback": used_lexical_fallback,
        "next_step": _NEXT_STEP,
    }
    for hit in hits:
        candidate = {**hit, "content_truncated": False}
        if _fits(response, candidate, max_chars=max_chars):
            response["results"].append(candidate)
            response["total"] = len(response["results"])
            continue

        response["results_truncated"] = True
        truncated = _truncate_hit_to_fit(response, candidate, max_chars=max_chars)
        if truncated is not None:
            response["results"].append(truncated)
            response["total"] = len(response["results"])
        break

    if len(response["results"]) < len(hits):
        response["results_truncated"] = True
    return response


def _truncate_hit_to_fit(
    response: dict[str, Any],
    hit: dict[str, Any],
    *,
    max_chars: int,
) -> dict[str, Any] | None:
    content = str(hit["content"])
    low = 0
    high = len(content)
    best: dict[str, Any] | None = None
    while low <= high:
        midpoint = (low + high) // 2
        candidate = {
            **hit,
            "content": f"{content[:midpoint].rstrip()}{_TRUNCATION_MARKER}",
            "content_truncated": True,
        }
        if _fits(response, candidate, max_chars=max_chars):
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    return best


def _fits(
    response: dict[str, Any],
    hit: dict[str, Any],
    *,
    max_chars: int,
) -> bool:
    candidate = {
        **response,
        "results": [*response["results"], hit],
        "total": len(response["results"]) + 1,
    }
    return (
        len(
            json.dumps(
                candidate,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        )
        <= max_chars
    )
