# apps/api/tests/services/embeddings/test_ollama_provider.py

"""Ollama embedding provider tests with no network access."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from services.embeddings.domain import EmbeddingConfigurationError
from services.embeddings.providers.ollama import OllamaEmbeddingsProvider


def test_ollama_provider_requires_an_explicit_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("services.embeddings.providers.ollama")
    monkeypatch.setattr(module.settings, "EMBEDDINGS_OLLAMA_BASE_URL", None)

    with pytest.raises(EmbeddingConfigurationError, match="EMBEDDINGS_OLLAMA_BASE_URL"):
        OllamaEmbeddingsProvider()


async def test_ollama_provider_posts_batch_and_estimates_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("services.embeddings.providers.ollama")
    response = SimpleNamespace(
        raise_for_status=Mock(),
        json=Mock(return_value={"embeddings": [[1.0, 0.0], [0.0, 1.0]]}),
    )
    client = SimpleNamespace(post=AsyncMock(return_value=response))
    monkeypatch.setattr(
        module.settings,
        "EMBEDDINGS_OLLAMA_BASE_URL",
        "http://127.0.0.1:11434/",
    )
    monkeypatch.setattr(module, "retrying_http_client", lambda: client)
    provider = OllamaEmbeddingsProvider()

    result = await provider.embed_texts(
        ["first", "second"],
        model="bge-m3",
        dimensions=1024,
    )

    client.post.assert_awaited_once_with(
        "http://127.0.0.1:11434/api/embed",
        json={"model": "bge-m3", "input": ["first", "second"]},
    )
    assert result.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert result.total_tokens == 2
