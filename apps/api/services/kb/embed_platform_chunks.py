# apps/api/services/kb/embed_platform_chunks.py

"""Fills platform vectors without exposing partial or stale materialisations."""

from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.settings import settings
from models.jobs import Job
from models.kb import KBChunk
from services.embeddings.domain import EmbeddingConfigurationError, EmbeddingProvider
from services.jobs.utils import sanitize_error_message
from services.kb.embedding import embed_chunk_batch
from services.kb.platform_job_utils import load_platform_job_document

_COLLECTION_LOCK_KEY = int.from_bytes(
    sha256(b"kb:platform:embedding-collection").digest()[:8], "big", signed=True
)


async def embed_platform_chunks(job: Job, *, provider: EmbeddingProvider | None = None) -> None:
    """Commits each completed batch after rechecking the unpublished version."""
    try:
        while True:
            async with maintenance_async_db_session() as db:
                document = await load_platform_job_document(db, job)
                if document is None:
                    return
                chunks = list(
                    (
                        await db.scalars(
                            select(KBChunk)
                            .where(
                                KBChunk.document_id == document.id,
                                KBChunk.scope == "platform",
                                KBChunk.embedding.is_(None),
                            )
                            .order_by(KBChunk.chunk_index)
                            .limit(settings.EMBEDDINGS_MAX_BATCH_TEXTS)
                        )
                    ).all()
                )
                if not chunks:
                    if document.chunk_count > 0:
                        document.status = "ready"
                        document.processing_error = None
                        document.meta = {
                            **document.meta,
                            "embedding_status": "ready",
                            "embedding_error": None,
                        }
                    return
                stamps = await _collection_stamps(db)
                db.expunge_all()
            async with maintenance_async_db_session() as db:
                result_stamp = await embed_chunk_batch(
                    db,
                    document=document,
                    batch=chunks,
                    collection_stamps=stamps,
                    provider=provider,
                    platform_user_id=job.initiated_by_user_id,
                )
            async with maintenance_async_db_session() as db:
                current = await load_platform_job_document(db, job)
                if current is None:
                    return
                await db.execute(select(func.pg_advisory_xact_lock(_COLLECTION_LOCK_KEY)))
                stamps = await _collection_stamps(db)
                if stamps and stamps != {result_stamp}:
                    raise EmbeddingConfigurationError(
                        "Embedding provider or model does not match the KB collection."
                    )
                stored_chunks = {
                    chunk.id: chunk
                    for chunk in await db.scalars(
                        select(KBChunk).where(
                            KBChunk.document_id == current.id,
                            KBChunk.scope == "platform",
                            KBChunk.id.in_([chunk.id for chunk in chunks]),
                        )
                    )
                }
                if len(stored_chunks) != len(chunks):
                    return
                for chunk in chunks:
                    stored = stored_chunks[chunk.id]
                    if stored.embedding is None:
                        stored.embedding = chunk.embedding
                        stored.embedding_provider = chunk.embedding_provider
                        stored.embedding_model = chunk.embedding_model
                        stored.embedding_dims = chunk.embedding_dims
    except Exception as exc:
        async with maintenance_async_db_session() as db:
            document = await load_platform_job_document(db, job)
            if document is not None:
                document.meta = {
                    **document.meta,
                    "embedding_status": "error",
                    "embedding_error": sanitize_error_message(str(exc) or type(exc).__name__),
                }
        raise


async def _collection_stamps(db: AsyncSession) -> set[tuple[str, str, int]]:
    return {
        tuple(row)
        for row in await db.execute(
            select(
                KBChunk.embedding_provider,
                KBChunk.embedding_model,
                KBChunk.embedding_dims,
            )
            .where(KBChunk.scope == "platform", KBChunk.embedding.is_not(None))
            .distinct()
        )
    }
