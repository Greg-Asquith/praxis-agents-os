# apps/api/services/embeddings/embed_texts.py

"""Public embedding service operation."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from services.embeddings.domain import (
    EmbeddingBatch,
    EmbeddingConfigurationError,
    EmbeddingProvider,
)
from services.embeddings.get_embedding_provider import get_embedding_provider
from services.embeddings.record_embedding_usage import record_embedding_usage
from services.embeddings.registry import get_embedding_model
from services.embeddings.utils import assert_batch_shape, chunk_batches


async def embed_texts(
    db: AsyncSession,
    texts: Sequence[str],
    *,
    workspace_id: UUID,
    provider: EmbeddingProvider | None = None,
) -> EmbeddingBatch:
    """Embed texts in order and meter every successful provider call."""
    model = settings.EMBEDDINGS_MODEL
    dimensions = settings.EMBEDDINGS_DIMENSIONS
    provider_key = provider.provider if provider is not None else settings.EMBEDDINGS_PROVIDER

    if not texts:
        return EmbeddingBatch(
            vectors=[],
            total_tokens=0,
            provider=provider_key,
            model=model,
            dimensions=dimensions,
        )

    for index, text in enumerate(texts):
        if not text.strip():
            raise EmbeddingConfigurationError(
                f"Embedding input at index {index} is empty.",
                details={"index": index},
            )
        if len(text) > settings.EMBEDDINGS_MAX_TEXT_CHARS:
            raise EmbeddingConfigurationError(
                f"Embedding input at index {index} exceeds the character limit.",
                details={
                    "index": index,
                    "max_characters": settings.EMBEDDINGS_MAX_TEXT_CHARS,
                },
            )

    info = get_embedding_model(settings.EMBEDDINGS_PROVIDER, model)
    if not info.supports_dimensions and dimensions != info.native_dimensions:
        raise EmbeddingConfigurationError(
            (
                f"Embedding model '{info.qualified_id}' requires "
                f"{info.native_dimensions} dimensions."
            ),
            details={
                "provider": info.provider,
                "model": info.model,
                "dimensions": dimensions,
                "native_dimensions": info.native_dimensions,
            },
        )

    resolved_provider = provider or get_embedding_provider()
    batch_size = min(settings.EMBEDDINGS_MAX_BATCH_TEXTS, info.max_batch_texts)
    vectors: list[list[float]] = []
    total_tokens = 0
    for text_batch in chunk_batches(texts, batch_size):
        result = await resolved_provider.embed_texts(
            text_batch,
            model=model,
            dimensions=dimensions,
        )
        assert_batch_shape(result, len(text_batch))
        vectors.extend(result.vectors)
        total_tokens += result.total_tokens

    combined = EmbeddingBatch(
        vectors=vectors,
        total_tokens=total_tokens,
        provider=resolved_provider.provider,
        model=model,
        dimensions=dimensions,
    )
    assert_batch_shape(combined, len(texts))
    await record_embedding_usage(
        db,
        workspace_id=workspace_id,
        tokens=total_tokens,
    )
    return combined
