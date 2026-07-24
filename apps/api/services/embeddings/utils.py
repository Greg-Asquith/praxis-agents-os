# apps/api/services/embeddings/utils.py

"""Pure helpers shared by embedding service operations."""

from collections.abc import Sequence
from datetime import UTC, date, datetime

from services.embeddings.domain import EmbeddingBatch, EmbeddingProviderError


def chunk_batches[T](values: Sequence[T], size: int) -> list[Sequence[T]]:
    """Split a sequence into order-preserving batches."""
    return [values[start : start + size] for start in range(0, len(values), size)]


def current_period_month() -> date:
    """Return the first day of the current UTC month."""
    now = datetime.now(UTC)
    return date(now.year, now.month, 1)


def assert_batch_shape(batch: EmbeddingBatch, expected_len: int) -> None:
    """Reject provider responses that violate the order/length contract."""
    if len(batch.vectors) != expected_len:
        raise EmbeddingProviderError(
            "Embedding provider returned an unexpected number of vectors.",
            details={
                "provider": batch.provider,
                "model": batch.model,
                "expected_vectors": expected_len,
                "actual_vectors": len(batch.vectors),
            },
        )
