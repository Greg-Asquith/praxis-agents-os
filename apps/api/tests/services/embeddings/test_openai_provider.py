# apps/api/tests/services/embeddings/test_openai_provider.py

"""OpenAI embedding provider tests with no network access."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import openai
import pytest

from services.embeddings.domain import EmbeddingProviderError
from services.embeddings.providers.openai import OpenAIEmbeddingsProvider


async def test_openai_provider_sends_dimensions_and_restores_response_order() -> None:
    create = AsyncMock(
        return_value=SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.0, 1.0]),
                SimpleNamespace(index=0, embedding=[1.0, 0.0]),
            ],
            usage=SimpleNamespace(total_tokens=7),
        )
    )
    client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    provider = OpenAIEmbeddingsProvider(client=client)  # type: ignore[arg-type]

    result = await provider.embed_texts(
        ["first", "second"],
        model="text-embedding-3-small",
        dimensions=1024,
    )

    assert result.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert result.total_tokens == 7
    create.assert_awaited_once_with(
        model="text-embedding-3-small",
        input=["first", "second"],
        encoding_format="float",
        dimensions=1024,
    )


async def test_openai_provider_maps_api_errors_without_input_text() -> None:
    private_text = "private document content"
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    create = AsyncMock(side_effect=openai.APIConnectionError(request=request))
    client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    provider = OpenAIEmbeddingsProvider(client=client)  # type: ignore[arg-type]

    with pytest.raises(EmbeddingProviderError) as caught:
        await provider.embed_texts(
            [private_text],
            model="text-embedding-3-small",
            dimensions=1024,
        )

    assert private_text not in str(caught.value)
    assert private_text not in repr(caught.value.details)
