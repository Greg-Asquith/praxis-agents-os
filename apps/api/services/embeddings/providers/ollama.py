# apps/api/services/embeddings/providers/ollama.py

"""Ollama embedding provider."""

from collections.abc import Sequence
from typing import Any

import httpx

from core.settings import settings
from services.agents.models import retrying_http_client
from services.embeddings.domain import (
    EMBEDDING_PROVIDER_OLLAMA,
    EmbeddingBatch,
    EmbeddingConfigurationError,
    EmbeddingProvider,
    EmbeddingProviderError,
)


class OllamaEmbeddingsProvider(EmbeddingProvider):
    """Embed text through an explicitly configured local Ollama server."""

    provider = EMBEDDING_PROVIDER_OLLAMA

    def __init__(self) -> None:
        base_url = (settings.EMBEDDINGS_OLLAMA_BASE_URL or "").strip()
        if not base_url:
            raise EmbeddingConfigurationError(
                "Ollama embeddings require EMBEDDINGS_OLLAMA_BASE_URL.",
                details={"provider": self.provider},
            )
        self._url = f"{base_url.rstrip('/')}/api/embed"
        self._client = retrying_http_client()

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int,
    ) -> EmbeddingBatch:
        try:
            response = await self._client.post(
                self._url,
                json={"model": model, "input": list(texts)},
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            vectors = [list(vector) for vector in payload["embeddings"]]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise EmbeddingProviderError(
                "Ollama embedding request failed.",
                details={"provider": self.provider, "model": model},
            ) from exc

        # Ollama does not report usage; this conservative character estimate
        # keeps local-provider usage visible under the same soft counter.
        total_tokens = sum(len(text) // 4 for text in texts)
        return EmbeddingBatch(
            vectors=vectors,
            total_tokens=total_tokens,
            provider=self.provider,
            model=model,
            dimensions=dimensions,
        )
