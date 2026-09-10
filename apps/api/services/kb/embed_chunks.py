# apps/api/services/kb/embed_chunks.py

"""Fill missing knowledge-base chunk embeddings."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.kb import KBChunk, KBDocument
from services.embeddings.domain import EmbeddingConfigurationError, EmbeddingProvider
from services.embeddings.utils import chunk_batches
from services.kb.domain import KB_COLLECTION_DIMS
from services.kb.embedding import embed_chunk_batch
from services.kb.utils import require_kb_workspace_id


async def embed_kb_chunks(
    db: AsyncSession,
    *,
    document_id: UUID,
    workspace_id: UUID | None,
    provider: EmbeddingProvider | None = None,
) -> None:
    """Embed only chunks still missing collection vectors."""
    workspace_id = require_kb_workspace_id(workspace_id)
    if settings.EMBEDDINGS_DIMENSIONS != KB_COLLECTION_DIMS:
        raise EmbeddingConfigurationError(
            "Knowledge-base collection dimensions do not match embedding settings.",
            details={
                "collection_dimensions": KB_COLLECTION_DIMS,
                "configured_dimensions": settings.EMBEDDINGS_DIMENSIONS,
            },
        )

    document_stmt = select(KBDocument).where(
        KBDocument.id == document_id,
        KBDocument.workspace_id == workspace_id,
        KBDocument.deleted.is_(False),
    )
    document = await db.scalar(document_stmt)
    if document is None:
        return

    chunks = (
        await db.scalars(
            select(KBChunk)
            .where(
                KBChunk.document_id == document.id,
                KBChunk.embedding.is_(None),
            )
            .order_by(KBChunk.chunk_index)
        )
    ).all()
    collection_stamps = {
        tuple(row)
        for row in (
            await db.execute(
                select(
                    KBChunk.embedding_provider,
                    KBChunk.embedding_model,
                    KBChunk.embedding_dims,
                )
                .where(KBChunk.embedding.is_not(None))
                .distinct()
            )
        ).all()
    }
    if len(collection_stamps) > 1:
        raise EmbeddingConfigurationError(
            "Knowledge-base collection already contains mixed embedding metadata."
        )

    for batch in chunk_batches(chunks, settings.EMBEDDINGS_MAX_BATCH_TEXTS):
        result_stamp = await embed_chunk_batch(
            db,
            document=document,
            batch=batch,
            collection_stamps=collection_stamps,
            provider=provider,
        )
        collection_stamps.add(result_stamp)
        await db.commit()
