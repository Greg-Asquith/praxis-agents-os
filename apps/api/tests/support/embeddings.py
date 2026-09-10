# apps/api/tests/support/embeddings.py

"""Deterministic, offline embedding provider for retrieval tests."""

import hashlib
import math
import random
import re
from collections.abc import Sequence

from services.embeddings.domain import (
    EmbeddingBatch,
    EmbeddingProvider,
    EmbeddingProviderPartialUsageError,
)

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return [1.0, *([0.0] * (len(values) - 1))]
    return [value / norm for value in values]


class FakeEmbeddingProvider(EmbeddingProvider):
    """Project token hashes into deterministic unit vectors without network I/O."""

    provider = "fake"

    def __init__(self, *, dimensions: int = 1024) -> None:
        self.dimensions = dimensions

    def _embed(self, text: str) -> list[float]:
        tokens = _TOKEN_PATTERN.findall(text.lower())
        if not tokens:
            return [1.0, *([0.0] * (self.dimensions - 1))]

        combined = [0.0] * self.dimensions
        for token in tokens:
            seed = hashlib.sha256(token.encode()).digest()
            generator = random.Random(seed)  # noqa: S311 - deterministic test projection
            token_vector = _normalize([generator.gauss(0.0, 1.0) for _ in range(self.dimensions)])
            for index, value in enumerate(token_vector):
                combined[index] += value
        return _normalize(combined)

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int,
    ) -> EmbeddingBatch:
        if dimensions != self.dimensions:
            raise ValueError(
                f"Fake provider configured for {self.dimensions}, received {dimensions}."
            )
        return EmbeddingBatch(
            vectors=[self._embed(text) for text in texts],
            total_tokens=sum(len(text) // 4 for text in texts),
            provider=self.provider,
            model=model,
            dimensions=dimensions,
        )


class RecordingProvider(EmbeddingProvider):
    provider = "recording"

    def __init__(self, *, omit_last: bool = False) -> None:
        self.call_sizes: list[int] = []
        self.omit_last = omit_last

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int,
    ) -> EmbeddingBatch:
        self.call_sizes.append(len(texts))
        vectors = [[float(index)] * dimensions for index in range(len(texts))]
        if self.omit_last:
            vectors = vectors[:-1]
        return EmbeddingBatch(
            vectors=vectors,
            total_tokens=len(texts) * 3,
            provider=self.provider,
            model=model,
            dimensions=dimensions,
        )


class PartialUsageFailingProvider(RecordingProvider):
    async def embed_texts(self, texts, *, model, dimensions):
        raise EmbeddingProviderPartialUsageError(
            "second request failed",
            input_tokens=4,
            requests=1,
        )
