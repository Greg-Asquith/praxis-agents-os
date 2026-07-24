# apps/api/tests/services/embeddings/test_google_provider.py

"""Google Gemini embedding provider tests with no network access."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from core.settings import settings
from services.embeddings.domain import EmbeddingProviderError
from services.embeddings.get_embedding_provider import get_embedding_provider
from services.embeddings.providers.google import GoogleEmbeddingsProvider


def test_embedding_provider_factory_selects_google(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("services.embeddings.get_embedding_provider")
    sentinel = Mock()
    google_provider = Mock(return_value=sentinel)
    monkeypatch.setattr(settings, "EMBEDDINGS_PROVIDER", "google")
    monkeypatch.setattr(module, "GoogleEmbeddingsProvider", google_provider)

    assert get_embedding_provider() is sentinel
    google_provider.assert_called_once_with()


async def test_google_provider_posts_ordered_batch_with_dimensions_and_usage() -> None:
    response = SimpleNamespace(
        raise_for_status=Mock(),
        json=Mock(
            return_value={
                "embeddings": [
                    {"values": [1.0, 0.0]},
                    {"values": [0.0, 1.0]},
                ],
                "usageMetadata": {"promptTokenCount": 7},
            }
        ),
    )
    client = SimpleNamespace(post=AsyncMock(return_value=response))
    provider = GoogleEmbeddingsProvider(
        client=client,  # type: ignore[arg-type]
        api_key="google-test",
    )

    result = await provider.embed_texts(
        ["first", "second"],
        model="gemini-embedding-2",
        dimensions=1024,
    )

    client.post.assert_awaited_once_with(
        (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-embedding-2:batchEmbedContents"
        ),
        headers={"x-goog-api-key": "google-test"},
        json={
            "requests": [
                {
                    "model": "models/gemini-embedding-2",
                    "content": {"parts": [{"text": "first"}]},
                    "embedContentConfig": {"outputDimensionality": 1024},
                },
                {
                    "model": "models/gemini-embedding-2",
                    "content": {"parts": [{"text": "second"}]},
                    "embedContentConfig": {"outputDimensionality": 1024},
                },
            ]
        },
    )
    assert result.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert result.total_tokens == 7
    assert result.provider == "google"


async def test_google_provider_maps_api_errors_without_input_or_key() -> None:
    private_text = "private document content"
    api_key = "private-google-key"
    request = httpx.Request(
        "POST",
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-embedding-2:batchEmbedContents",
    )
    client = SimpleNamespace(
        post=AsyncMock(side_effect=httpx.ConnectError("failed", request=request))
    )
    provider = GoogleEmbeddingsProvider(
        client=client,  # type: ignore[arg-type]
        api_key=api_key,
    )

    with pytest.raises(EmbeddingProviderError) as caught:
        await provider.embed_texts(
            [private_text],
            model="gemini-embedding-2",
            dimensions=1024,
        )

    assert private_text not in str(caught.value)
    assert private_text not in repr(caught.value.details)
    assert api_key not in str(caught.value)
    assert api_key not in repr(caught.value.details)


@pytest.mark.parametrize(
    "payload",
    [
        {"embeddings": [{"values": [1.0]}]},
        {
            "embeddings": [{"values": [1.0]}],
            "usageMetadata": {"promptTokenCount": "1"},
        },
    ],
)
async def test_google_provider_rejects_missing_or_invalid_usage(payload: object) -> None:
    response = SimpleNamespace(
        raise_for_status=Mock(),
        json=Mock(return_value=payload),
    )
    client = SimpleNamespace(post=AsyncMock(return_value=response))
    provider = GoogleEmbeddingsProvider(
        client=client,  # type: ignore[arg-type]
        api_key="google-test",
    )

    with pytest.raises(EmbeddingProviderError, match="Google embedding request failed"):
        await provider.embed_texts(
            ["text"],
            model="gemini-embedding-2",
            dimensions=1024,
        )
