# apps/api/services/embeddings/registry.py

"""Python-owned catalog of supported embedding models."""

from dataclasses import dataclass

from services.embeddings.domain import (
    EMBEDDING_PROVIDER_GOOGLE,
    EMBEDDING_PROVIDER_OLLAMA,
    EMBEDDING_PROVIDER_OPENAI,
    EmbeddingConfigurationError,
)


@dataclass(frozen=True)
class EmbeddingModelInfo:
    """Provider metadata needed to validate and batch embedding calls."""

    provider: str
    model: str
    native_dimensions: int
    supports_dimensions: bool
    max_batch_texts: int

    @property
    def qualified_id(self) -> str:
        return f"{self.provider}:{self.model}"


_CATALOG: tuple[EmbeddingModelInfo, ...] = (
    EmbeddingModelInfo(
        provider=EMBEDDING_PROVIDER_OPENAI,
        model="text-embedding-3-small",
        native_dimensions=1536,
        supports_dimensions=True,
        max_batch_texts=2048,
    ),
    # Deliberately truncation-only under the 1024-dimension storage ceiling:
    # at 1024 dimensions this remains a quality upgrade without a schema change.
    EmbeddingModelInfo(
        provider=EMBEDDING_PROVIDER_OPENAI,
        model="text-embedding-3-large",
        native_dimensions=3072,
        supports_dimensions=True,
        max_batch_texts=2048,
    ),
    EmbeddingModelInfo(
        provider=EMBEDDING_PROVIDER_GOOGLE,
        model="gemini-embedding-2",
        native_dimensions=3072,
        supports_dimensions=True,
        max_batch_texts=64,
    ),
    EmbeddingModelInfo(
        provider=EMBEDDING_PROVIDER_OLLAMA,
        model="bge-m3",
        native_dimensions=1024,
        supports_dimensions=False,
        max_batch_texts=64,
    ),
)
_INDEX = {(item.provider, item.model): item for item in _CATALOG}


def get_embedding_model(provider: str, model: str) -> EmbeddingModelInfo:
    """Return one known provider/model pair."""
    info = _INDEX.get((provider, model))
    if info is None:
        raise EmbeddingConfigurationError(
            f"Unknown embedding model '{provider}:{model}'.",
            details={"provider": provider, "model": model},
        )
    return info


def list_embedding_models() -> tuple[EmbeddingModelInfo, ...]:
    """Return the immutable embedding-model catalog."""
    return _CATALOG
