# apps/api/tests/services/embeddings/test_registry.py

"""Embedding-model registry contract tests."""

from uuid import uuid4

import pytest

from core.settings import settings
from services.agents.models.domain import PROVIDER_GOOGLE, PROVIDER_OPENAI
from services.ai_usage.domain import PURPOSE_EMBEDDING_KB_SEARCH
from services.embeddings.domain import (
    EMBEDDING_PROVIDER_GOOGLE,
    EMBEDDING_PROVIDER_OPENAI,
    EmbeddingConfigurationError,
)
from services.embeddings.embed_texts import embed_texts
from services.embeddings.registry import get_embedding_model, list_embedding_models
from tests.support.embeddings import FakeEmbeddingProvider


def test_registry_lists_known_models_and_provider_key_matches_credential_seam() -> None:
    qualified_ids = {item.qualified_id for item in list_embedding_models()}

    assert "openai:text-embedding-3-small" in qualified_ids
    assert "openai:text-embedding-3-large" in qualified_ids
    assert "google:gemini-embedding-2" in qualified_ids
    assert "ollama:bge-m3" in qualified_ids
    assert EMBEDDING_PROVIDER_GOOGLE == PROVIDER_GOOGLE
    assert EMBEDDING_PROVIDER_OPENAI == PROVIDER_OPENAI


def test_registry_rejects_unknown_model() -> None:
    with pytest.raises(EmbeddingConfigurationError, match="Unknown embedding model"):
        get_embedding_model("openai", "unknown")


def test_every_catalog_entry_fits_the_storage_dimension_bounds() -> None:
    assert all(
        item.supports_dimensions or 512 <= item.native_dimensions <= 1024
        for item in list_embedding_models()
    )


async def test_non_truncatable_model_rejects_non_native_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EMBEDDINGS_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "EMBEDDINGS_MODEL", "bge-m3")
    monkeypatch.setattr(settings, "EMBEDDINGS_DIMENSIONS", 512)

    with pytest.raises(EmbeddingConfigurationError, match="requires 1024 dimensions"):
        await embed_texts(
            None,  # type: ignore[arg-type] - validation fails before DB access
            ["text"],
            workspace_id=uuid4(),
            purpose=PURPOSE_EMBEDDING_KB_SEARCH,
            provider=FakeEmbeddingProvider(dimensions=512),
        )
