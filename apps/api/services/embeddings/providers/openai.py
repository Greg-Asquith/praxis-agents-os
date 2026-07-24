# apps/api/services/embeddings/providers/openai.py

"""OpenAI embedding provider."""

from collections.abc import Sequence
from typing import Any

import httpx
import openai
from openai import AsyncOpenAI

from services.agents.models import provider_api_key, retrying_http_client
from services.agents.models.domain import PROVIDER_OPENAI
from services.embeddings.domain import (
    EMBEDDING_PROVIDER_OPENAI,
    EmbeddingBatch,
    EmbeddingProvider,
    EmbeddingProviderError,
)
from services.embeddings.registry import get_embedding_model


class OpenAIEmbeddingsProvider(EmbeddingProvider):
    """Embed text through the OpenAI embeddings API."""

    provider = EMBEDDING_PROVIDER_OPENAI

    def __init__(self, *, client: AsyncOpenAI | None = None) -> None:
        self._client = client or AsyncOpenAI(
            api_key=provider_api_key(PROVIDER_OPENAI),
            http_client=retrying_http_client(),
        )

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int,
    ) -> EmbeddingBatch:
        kwargs: dict[str, Any] = {
            "model": model,
            "input": list(texts),
            "encoding_format": "float",
        }
        if get_embedding_model(self.provider, model).supports_dimensions:
            kwargs["dimensions"] = dimensions

        try:
            response = await self._client.embeddings.create(**kwargs)
        except (openai.APIError, httpx.HTTPError) as exc:
            raise EmbeddingProviderError(
                "OpenAI embedding request failed.",
                details={"provider": self.provider, "model": model},
            ) from exc

        vectors = [
            list(item.embedding) for item in sorted(response.data, key=lambda item: item.index)
        ]
        return EmbeddingBatch(
            vectors=vectors,
            total_tokens=response.usage.total_tokens,
            provider=self.provider,
            model=model,
            dimensions=dimensions,
        )
