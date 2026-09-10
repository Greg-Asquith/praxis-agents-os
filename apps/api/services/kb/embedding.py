# apps/api/services/kb/embedding.py

"""Shared bounded embedding and collection validation for knowledge chunks."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.kb import KBChunk, KBDocument
from services.ai_usage.domain import PURPOSE_EMBEDDING_KB_INGEST
from services.embeddings import embed_texts
from services.embeddings.domain import EmbeddingConfigurationError, EmbeddingProvider
from services.kb.domain import KB_COLLECTION_DIMS
from utils.content import ContentScope


async def embed_chunk_batch(
    db: AsyncSession,
    *,
    document: KBDocument,
    batch: Sequence[KBChunk],
    collection_stamps: set[tuple[str, str, int]],
    provider: EmbeddingProvider | None = None,
    platform_user_id: UUID | None = None,
) -> tuple[str, str, int]:
    """Embeds and validates one bounded batch through the shared usage service."""
    if settings.EMBEDDINGS_DIMENSIONS != KB_COLLECTION_DIMS or len(collection_stamps) > 1:
        raise EmbeddingConfigurationError("Knowledge-base collection metadata is inconsistent")
    inputs = [
        f"{chunk.context_line}\n\n{chunk.content}" if chunk.context_line else chunk.content
        for chunk in batch
    ]
    result = await embed_texts(
        db,
        inputs,
        workspace_id=document.workspace_id,
        scope=ContentScope(document.scope or "workspace"),
        user_id=(platform_user_id if document.scope == ContentScope.PLATFORM else None),
        purpose=PURPOSE_EMBEDDING_KB_INGEST,
        provider=provider,
    )
    if result.dimensions != KB_COLLECTION_DIMS:
        raise EmbeddingConfigurationError(
            "Embedding provider returned dimensions outside the KB collection.",
            details={
                "collection_dimensions": KB_COLLECTION_DIMS,
                "returned_dimensions": result.dimensions,
            },
        )
    result_stamp = (result.provider, result.model, result.dimensions)
    if collection_stamps and result_stamp not in collection_stamps:
        existing_provider, existing_model, existing_dimensions = next(iter(collection_stamps))
        raise EmbeddingConfigurationError(
            "Embedding provider or model does not match the KB collection.",
            details={
                "existing_provider": existing_provider,
                "existing_model": existing_model,
                "existing_dimensions": existing_dimensions,
                "returned_provider": result.provider,
                "returned_model": result.model,
                "returned_dimensions": result.dimensions,
            },
        )
    for chunk, vector in zip(batch, result.vectors, strict=True):
        if len(vector) != KB_COLLECTION_DIMS:
            raise EmbeddingConfigurationError(
                "Embedding vector length does not match the KB collection.",
                details={
                    "chunk_id": str(chunk.id),
                    "collection_dimensions": KB_COLLECTION_DIMS,
                    "returned_dimensions": len(vector),
                },
            )
        chunk.embedding = vector
        chunk.embedding_provider = result.provider
        chunk.embedding_model = result.model
        chunk.embedding_dims = result.dimensions
    return result_stamp
