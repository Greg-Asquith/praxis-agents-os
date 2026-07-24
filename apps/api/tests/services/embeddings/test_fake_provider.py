# apps/api/tests/services/embeddings/test_fake_provider.py

"""Deterministic fake embedding-provider tests."""

import math

import pytest

from tests.support.embeddings import FakeEmbeddingProvider


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


async def test_fake_provider_is_deterministic_normalized_and_semantically_graded() -> None:
    provider = FakeEmbeddingProvider(dimensions=32)
    batch = await provider.embed_texts(
        [
            "vpn setup guide",
            "vpn setup guide",
            "how to set up the vpn",
            "quarterly revenue report",
        ],
        model="test",
        dimensions=32,
    )

    assert batch.vectors[0] == batch.vectors[1]
    assert all(
        math.sqrt(sum(value * value for value in vector)) == pytest.approx(1.0)
        for vector in batch.vectors
    )
    assert _cosine(batch.vectors[0], batch.vectors[2]) > _cosine(batch.vectors[0], batch.vectors[3])
