# apps/api/services/embeddings/providers/google.py

"""Google Gemini embedding provider."""

import asyncio
from collections.abc import Sequence
from typing import Any

import httpx
from google.genai import Client, errors, types

from core.settings import settings
from services.agents.models import provider_api_key, retrying_http_client
from services.agents.models.domain import PROVIDER_GOOGLE
from services.agents.models.vertex_clients import get_google_vertex_client
from services.embeddings.domain import (
    EMBEDDING_PROVIDER_GOOGLE,
    EmbeddingBatch,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingProviderPartialUsageError,
)

_GOOGLE_EMBEDDINGS_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_VERTEX_MAX_CONCURRENT_REQUESTS = 8
_VERTEX_REQUEST_ERRORS = (
    errors.APIError,
    httpx.HTTPError,
    KeyError,
    TypeError,
    ValueError,
)


class GoogleEmbeddingsProvider(EmbeddingProvider):
    """Embed text through the Google Gemini batch embeddings API."""

    provider = EMBEDDING_PROVIDER_GOOGLE

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        api_key: str | None = None,
        vertex_client: Client | None = None,
    ) -> None:
        if settings.GOOGLE_VERTEX_AI:
            self._vertex_client = vertex_client or get_google_vertex_client()
            self._client = None
            self._api_key = None
        else:
            self._vertex_client = None
            self._client = client or retrying_http_client()
            self._api_key = api_key or provider_api_key(PROVIDER_GOOGLE)

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int,
    ) -> EmbeddingBatch:
        if self._vertex_client is not None:
            return await self._embed_texts_vertex(
                texts,
                model=model,
                dimensions=dimensions,
            )

        return await self._embed_texts_developer_api(
            texts,
            model=model,
            dimensions=dimensions,
        )

    async def _embed_texts_developer_api(
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

    async def _embed_texts_vertex(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int,
    ) -> EmbeddingBatch:
        if self._vertex_client is None:
            raise RuntimeError("Vertex client is not configured.")

        results: list[tuple[list[float], int] | None] = [None] * len(texts)
        config = types.EmbedContentConfig(output_dimensionality=dimensions)
        next_index = 0
        first_error: BaseException | None = None

        async def embed_available_texts() -> None:
            nonlocal first_error, next_index
            while first_error is None:
                index = next_index
                if index >= len(texts):
                    return
                next_index += 1
                text = texts[index]
                try:
                    results[index] = await self._embed_vertex_text(
                        text,
                        model=model,
                        config=config,
                    )
                except _VERTEX_REQUEST_ERRORS as exc:
                    if first_error is None:
                        first_error = exc
                    return

        workers = [
            embed_available_texts() for _ in range(min(len(texts), _VERTEX_MAX_CONCURRENT_REQUESTS))
        ]
        await asyncio.gather(*workers)

        completed = [result for result in results if result is not None]
        total_tokens = sum(token_count for _, token_count in completed)
        if first_error is not None:
            raise EmbeddingProviderPartialUsageError(
                "Google embedding request failed.",
                input_tokens=total_tokens,
                requests=len(completed),
                details={"provider": self.provider, "model": model},
            ) from first_error

        vectors = [result[0] for result in completed]
        return EmbeddingBatch(
            vectors=vectors,
            total_tokens=total_tokens,
            provider=self.provider,
            model=model,
            dimensions=dimensions,
            requests=len(texts),
        )

    async def _embed_vertex_text(
        self,
        text: str,
        *,
        model: str,
        config: types.EmbedContentConfig,
    ) -> tuple[list[float], int]:
        if self._vertex_client is None:
            raise RuntimeError("Vertex client is not configured.")

        response = await self._vertex_client.aio.models.embed_content(
            model=model,
            contents=text,
            config=config,
        )
        embeddings = response.embeddings
        if embeddings is None or len(embeddings) != 1:
            raise ValueError("Vertex embedding response has an invalid shape.")
        embedding = embeddings[0]
        if embedding.values is None or embedding.statistics is None:
            raise ValueError("Vertex embedding response is incomplete.")
        token_count = embedding.statistics.token_count
        if (
            not isinstance(token_count, int | float)
            or isinstance(token_count, bool)
            or token_count < 0
            or not float(token_count).is_integer()
        ):
            raise TypeError("Vertex embedding usage is not an integer.")
        return list(embedding.values), int(token_count)
