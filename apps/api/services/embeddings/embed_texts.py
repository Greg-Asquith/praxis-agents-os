# apps/api/services/embeddings/embed_texts.py

"""Public embedding service operation."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from services.ai_usage.domain import AIUsageEventData, AIUsagePurpose
from services.ai_usage.record_durable import record_ai_usage_durable
from services.embeddings.domain import (
    EmbeddingBatch,
    EmbeddingConfigurationError,
    EmbeddingProvider,
    EmbeddingProviderPartialUsageError,
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
    purpose: AIUsagePurpose,
    agent_id: UUID | None = None,
    user_id: UUID | None = None,
    run_id: UUID | None = None,
    conversation_id: UUID | None = None,
    provider: EmbeddingProvider | None = None,
) -> EmbeddingBatch:
    """Embed texts in order and meter every successful provider call."""
    model = settings.EMBEDDINGS_MODEL
    dimensions = settings.EMBEDDINGS_DIMENSIONS
    provider_key = provider.provider if provider is not None else settings.EMBEDDINGS_PROVIDER
    # Validate the closed purpose and stable identity before any provider work.
    AIUsageEventData(
        workspace_id=workspace_id,
        provider=provider_key,
        model=model,
        purpose=purpose,
        agent_id=agent_id,
        user_id=user_id,
        run_id=run_id,
        conversation_id=conversation_id,
    )

    if not texts:
        return EmbeddingBatch(
            vectors=[],
            total_tokens=0,
            provider=provider_key,
            model=model,
            dimensions=dimensions,
            requests=0,
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

    owns_provider = provider is None
    resolved_provider = provider or get_embedding_provider()
    batch_size = min(settings.EMBEDDINGS_MAX_BATCH_TEXTS, info.max_batch_texts)
    vectors: list[list[float]] = []
    total_tokens = 0
    requests = 0
    try:
        for text_batch in chunk_batches(texts, batch_size):
            try:
                result = await resolved_provider.embed_texts(
                    text_batch,
                    model=model,
                    dimensions=dimensions,
                )
            except EmbeddingProviderPartialUsageError as exc:
                total_tokens += exc.input_tokens
                requests += exc.requests
                raise
            if isinstance(result.total_tokens, bool) or result.total_tokens < 0:
                raise EmbeddingConfigurationError("Embedding provider returned invalid usage.")
            if (
                not isinstance(result.requests, int)
                or isinstance(result.requests, bool)
                or result.requests < 1
            ):
                raise EmbeddingConfigurationError(
                    "Embedding provider returned an invalid request count."
                )
            total_tokens += result.total_tokens
            requests += result.requests
            assert_batch_shape(result, len(text_batch))
            vectors.extend(result.vectors)
    finally:
        try:
            if owns_provider:
                await resolved_provider.aclose()
        finally:
            await record_ai_usage_durable(
                AIUsageEventData(
                    workspace_id=workspace_id,
                    provider=resolved_provider.provider,
                    model=model,
                    purpose=purpose,
                    input_tokens=total_tokens,
                    requests=requests,
                    agent_id=agent_id,
                    user_id=user_id,
                    run_id=run_id,
                    conversation_id=conversation_id,
                )
            )

    combined = EmbeddingBatch(
        vectors=vectors,
        total_tokens=total_tokens,
        provider=resolved_provider.provider,
        model=model,
        dimensions=dimensions,
        requests=requests,
    )
    assert_batch_shape(combined, len(texts))
    await record_embedding_usage(
        db,
        workspace_id=workspace_id,
        tokens=total_tokens,
    )
    return combined
