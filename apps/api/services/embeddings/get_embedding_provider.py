# apps/api/services/embeddings/get_embedding_provider.py

"""Embedding-provider factory operation."""

from core.settings import settings
from services.embeddings.domain import EmbeddingConfigurationError, EmbeddingProvider
from services.embeddings.providers import (
    GoogleEmbeddingsProvider,
    OllamaEmbeddingsProvider,
    OpenAIEmbeddingsProvider,
)


def get_embedding_provider() -> EmbeddingProvider:
    """Build the configured provider; kept uncached for simple test injection."""
    if settings.EMBEDDINGS_PROVIDER == "openai":
        return OpenAIEmbeddingsProvider()
    if settings.EMBEDDINGS_PROVIDER == "google":
        return GoogleEmbeddingsProvider()
    if settings.EMBEDDINGS_PROVIDER == "ollama":
        return OllamaEmbeddingsProvider()
    raise EmbeddingConfigurationError(
        f"Unknown embedding provider '{settings.EMBEDDINGS_PROVIDER}'.",
        details={"provider": settings.EMBEDDINGS_PROVIDER},
    )
