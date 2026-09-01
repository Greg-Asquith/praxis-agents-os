# apps/api/services/embeddings/domain.py

"""Embedding provider contracts, values, and typed failures."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from core.exceptions.general import ProblemDetailsError

EMBEDDING_PROVIDER_OPENAI = "openai"
EMBEDDING_PROVIDER_GOOGLE = "google"
EMBEDDING_PROVIDER_OLLAMA = "ollama"


@dataclass(frozen=True)
class EmbeddingBatch:
    """An order-preserving provider embedding response."""

    vectors: list[list[float]]
    total_tokens: int
    provider: str
    model: str
    dimensions: int
    requests: int = 1


class EmbeddingProvider(ABC):
    """Batch-first interface implemented by every embedding provider."""

    provider: ClassVar[str]

    @abstractmethod
    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int,
    ) -> EmbeddingBatch:
        """Embed texts in input order."""

    async def aclose(self) -> None:
        """Releases resources owned by the provider."""
        return


class EmbeddingConfigurationError(ProblemDetailsError):
    """Raised for an invalid provider, model, dimension, or caller input."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(
            message,
            status_code=500,
            title="Embedding Configuration Error",
            details=details,
        )


class EmbeddingProviderError(ProblemDetailsError):
    """Raised after an embedding provider or its retry transport fails."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(
            message,
            status_code=502,
            title="Embedding Provider Error",
            details=details,
        )


class EmbeddingProviderPartialUsageError(EmbeddingProviderError):
    """Carries known usage from completed requests before a provider failure."""

    def __init__(
        self,
        message: str,
        *,
        input_tokens: int,
        requests: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.input_tokens = input_tokens
        self.requests = requests
