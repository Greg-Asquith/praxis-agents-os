# apps/api/tests/services/embeddings/test_registry.py

"""Embedding-model registry contract tests."""

from uuid import uuid4

import pytest

from core.settings import settings
from services.ai_usage.domain import PURPOSE_EMBEDDING_KB_SEARCH
from services.embeddings.domain import (
    EmbeddingConfigurationError,
)
from services.embeddings.embed_texts import embed_texts
from services.embeddings.registry import list_embedding_models
from tests.support.embeddings import FakeEmbeddingProvider


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
