# apps/api/services/embeddings/get_embedding_provider.py

"""Embedding-provider factory operation."""

from core.settings import settings
from services.embeddings.domain import EmbeddingConfigurationError, EmbeddingProvider


def get_embedding_provider() -> EmbeddingProvider:
    """Build the configured provider; kept uncached for simple test injection."""
    # Each provider imports its SDK on first use, so only the configured one loads.
    if settings.EMBEDDINGS_PROVIDER == "openai":
        from services.embeddings.providers.openai import OpenAIEmbeddingsProvider

        return OpenAIEmbeddingsProvider()
    if settings.EMBEDDINGS_PROVIDER == "google":
        from services.embeddings.providers.google import GoogleEmbeddingsProvider

        return GoogleEmbeddingsProvider()
    if settings.EMBEDDINGS_PROVIDER == "ollama":
        from services.embeddings.providers.ollama import OllamaEmbeddingsProvider

        return OllamaEmbeddingsProvider()
    raise EmbeddingConfigurationError(
        f"Unknown embedding provider '{settings.EMBEDDINGS_PROVIDER}'.",
        details={"provider": settings.EMBEDDINGS_PROVIDER},
    )
