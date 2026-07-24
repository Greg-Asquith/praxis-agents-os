# apps/api/services/embeddings/providers/google.py

"""Google Gemini embedding provider."""

from collections.abc import Sequence
from typing import Any

import httpx

from services.agents.models import provider_api_key, retrying_http_client
from services.agents.models.domain import PROVIDER_GOOGLE
from services.embeddings.domain import (
    EMBEDDING_PROVIDER_GOOGLE,
    EmbeddingBatch,
    EmbeddingProvider,
    EmbeddingProviderError,
)

_GOOGLE_EMBEDDINGS_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GoogleEmbeddingsProvider(EmbeddingProvider):
    """Embed text through the Google Gemini batch embeddings API."""

    provider = EMBEDDING_PROVIDER_GOOGLE

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        api_key: str | None = None,
    ) -> None:
        self._client = client or retrying_http_client()
        self._api_key = api_key or provider_api_key(PROVIDER_GOOGLE)

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int,
    ) -> EmbeddingBatch:
        model_resource = f"models/{model}"
        requests = [
            {
                "model": model_resource,
                "content": {"parts": [{"text": text}]},
                "embedContentConfig": {"outputDimensionality": dimensions},
            }
            for text in texts
        ]

        try:
            response = await self._client.post(
                f"{_GOOGLE_EMBEDDINGS_BASE_URL}/{model}:batchEmbedContents",
                headers={"x-goog-api-key": self._api_key},
                json={"requests": requests},
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            vectors = [list(item["values"]) for item in payload["embeddings"]]
            total_tokens = payload["usageMetadata"]["promptTokenCount"]
            if not isinstance(total_tokens, int) or isinstance(total_tokens, bool):
                raise TypeError("Google embedding usage is not an integer.")
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise EmbeddingProviderError(
                "Google embedding request failed.",
                details={"provider": self.provider, "model": model},
            ) from exc

        return EmbeddingBatch(
            vectors=vectors,
            total_tokens=total_tokens,
            provider=self.provider,
            model=model,
            dimensions=dimensions,
        )
