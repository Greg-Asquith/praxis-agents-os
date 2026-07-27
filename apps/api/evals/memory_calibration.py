# apps/api/evals/memory_calibration/.py

"""Opt-in live calibration for memory near-duplicate resolution."""

import asyncio
import json
import math
import sys

from core.settings import settings
from services.embeddings.domain import EmbeddingProvider
from services.embeddings.get_embedding_provider import get_embedding_provider

MEMORY_DEDUP_CALIBRATION_PAIRS = (
    (
        "duplicate",
        "The client prefers concise weekly reports.",
        "The client prefers concise weekly reports.",
    ),
    (
        "contradiction",
        "The client strongly prefers concise weekly reports with the key account "
        "figures, delivery risks, next actions, and owners listed first.",
        "The client does not strongly prefer concise weekly reports with the key "
        "account figures, delivery risks, next actions, and owners listed first.",
    ),
    (
        "distinct",
        "The client prefers concise weekly reports.",
        "Invoices are paid on the fifteenth day of each month.",
    ),
)


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        math.sqrt(sum(value * value for value in left))
        * math.sqrt(sum(value * value for value in right))
    )


async def calibrate_memory_dedup(
    provider: EmbeddingProvider | None = None,
) -> dict[str, float]:
    """Return labeled cosine scores from the configured embedding collection."""
    resolved_provider = provider or get_embedding_provider()
    vectors = await resolved_provider.embed_texts(
        [text for _label, left, right in MEMORY_DEDUP_CALIBRATION_PAIRS for text in (left, right)],
        model=settings.EMBEDDINGS_MODEL,
        dimensions=settings.EMBEDDINGS_DIMENSIONS,
    )
    return {
        label: _cosine(
            vectors.vectors[index * 2],
            vectors.vectors[index * 2 + 1],
        )
        for index, (label, _left, _right) in enumerate(MEMORY_DEDUP_CALIBRATION_PAIRS)
    }


async def main() -> None:
    """Print calibration evidence and fail when the pinned boundary drifts."""
    scores = await calibrate_memory_dedup()
    sys.stdout.write(
        json.dumps(
            {
                "provider": settings.EMBEDDINGS_PROVIDER,
                "model": settings.EMBEDDINGS_MODEL,
                "dimensions": settings.EMBEDDINGS_DIMENSIONS,
                "threshold": settings.MEMORY_DEDUP_SIMILARITY,
                "scores": scores,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if scores["duplicate"] < settings.MEMORY_DEDUP_SIMILARITY:
        raise SystemExit("Duplicate calibration pair fell below the configured threshold")
    if scores["contradiction"] < settings.MEMORY_DEDUP_SIMILARITY:
        raise SystemExit("Contradiction calibration pair fell below the configured threshold")
    if scores["contradiction"] <= scores["distinct"]:
        raise SystemExit("Contradiction calibration no longer outranks the distinct pair")


if __name__ == "__main__":
    asyncio.run(main())
