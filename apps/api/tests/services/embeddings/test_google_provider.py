# apps/api/tests/services/embeddings/test_google_provider.py

"""Google Gemini embedding provider tests with no network access."""

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx2 as httpx
import pytest
from google.genai import types

from core.settings import settings
from services.agents.models.domain import ModelConfigurationError
from services.embeddings.domain import (
    EmbeddingProviderError,
    EmbeddingProviderPartialUsageError,
)
from services.embeddings.get_embedding_provider import get_embedding_provider
from services.embeddings.providers.google import GoogleEmbeddingsProvider


@pytest.fixture(autouse=True)
def _use_developer_api_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", False)


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


async def test_google_vertex_provider_preserves_order_dimensions_and_real_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", True)
    embed_content = AsyncMock(
        side_effect=[
            SimpleNamespace(
                embeddings=[
                    SimpleNamespace(
                        values=[1.0, 0.0],
                        statistics=SimpleNamespace(token_count=3.0),
                    )
                ]
            ),
            SimpleNamespace(
                embeddings=[
                    SimpleNamespace(
                        values=[0.0, 1.0],
                        statistics=SimpleNamespace(token_count=4.0),
                    )
                ]
            ),
        ]
    )
    vertex_client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(embed_content=embed_content))
    )
    provider = GoogleEmbeddingsProvider(vertex_client=vertex_client)  # type: ignore[arg-type]

    result = await provider.embed_texts(
        ["first", "second"],
        model="gemini-embedding-2",
        dimensions=1024,
    )

    assert [call.kwargs["contents"] for call in embed_content.await_args_list] == [
        "first",
        "second",
    ]
    assert all(
        call.kwargs["model"] == "gemini-embedding-2" for call in embed_content.await_args_list
    )
    assert all(
        call.kwargs["config"] == types.EmbedContentConfig(output_dimensionality=1024)
        for call in embed_content.await_args_list
    )
    assert result.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert result.total_tokens == 7
    assert result.dimensions == 1024
    assert result.requests == 2


async def test_google_vertex_provider_runs_requests_concurrently_with_a_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", True)
    active_requests = 0
    peak_requests = 0
    concurrent_requests_started = asyncio.Event()

    async def embed_content(*, contents: str, **_kwargs: object) -> object:
        nonlocal active_requests, peak_requests
        active_requests += 1
        peak_requests = max(peak_requests, active_requests)
        if active_requests >= 2:
            concurrent_requests_started.set()
        await concurrent_requests_started.wait()
        await asyncio.sleep(0)
        active_requests -= 1
        return SimpleNamespace(
            embeddings=[
                SimpleNamespace(
                    values=[float(contents)],
                    statistics=SimpleNamespace(token_count=1),
                )
            ]
        )

    vertex_client = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(embed_content=AsyncMock(side_effect=embed_content))
        )
    )
    provider = GoogleEmbeddingsProvider(vertex_client=vertex_client)  # type: ignore[arg-type]

    result = await provider.embed_texts(
        [str(index) for index in range(10)],
        model="gemini-embedding-2",
        dimensions=1024,
    )

    assert 1 < peak_requests <= 8
    assert result.vectors == [[float(index)] for index in range(10)]
    assert result.requests == 10


async def test_google_vertex_provider_carries_usage_when_second_request_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", True)
    first_response = SimpleNamespace(
        embeddings=[
            SimpleNamespace(
                values=[1.0],
                statistics=SimpleNamespace(token_count=3),
            )
        ]
    )
    embed_content = AsyncMock(side_effect=[first_response, ValueError("failed")])
    vertex_client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(embed_content=embed_content))
    )
    provider = GoogleEmbeddingsProvider(vertex_client=vertex_client)  # type: ignore[arg-type]

    with pytest.raises(EmbeddingProviderPartialUsageError) as caught:
        await provider.embed_texts(
            ["first", "second"],
            model="gemini-embedding-2",
            dimensions=1024,
        )

    assert caught.value.input_tokens == 3
    assert caught.value.requests == 1


@pytest.mark.parametrize("token_count", [None, 1.5, True])
async def test_google_vertex_provider_rejects_invalid_usage(
    monkeypatch: pytest.MonkeyPatch,
    token_count: object,
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", True)
    response = SimpleNamespace(
        embeddings=[
            SimpleNamespace(
                values=[1.0],
                statistics=SimpleNamespace(token_count=token_count),
            )
        ]
    )
    vertex_client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(embed_content=AsyncMock(return_value=response)))
    )
    provider = GoogleEmbeddingsProvider(vertex_client=vertex_client)  # type: ignore[arg-type]

    with pytest.raises(EmbeddingProviderError, match="Google embedding request failed"):
        await provider.embed_texts(
            ["text"],
            model="gemini-embedding-2",
            dimensions=1024,
        )


def test_google_vertex_provider_requires_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", None)
    monkeypatch.setattr(settings, "GCP_PROJECT_ID", None)

    with pytest.raises(ModelConfigurationError, match="GOOGLE_VERTEX_PROJECT"):
        GoogleEmbeddingsProvider()


async def test_google_vertex_provider_leaves_client_for_process_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("services.embeddings.providers.google")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", True)
    shared_close = AsyncMock()
    shared_client = SimpleNamespace(aio=SimpleNamespace(aclose=shared_close))
    monkeypatch.setattr(module, "get_google_vertex_client", Mock(return_value=shared_client))

    provider = GoogleEmbeddingsProvider()
    await provider.aclose()

    assert provider._vertex_client is shared_client
    shared_close.assert_not_awaited()
