# apps/api/services/kb/ingest_document.py

"""Ingest one knowledge-base document into lexical chunks."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic_ai.models import Model
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.kb import KBChunk, KBDocument
from services.jobs.utils import sanitize_error_message
from services.kb.annotation import annotate_chunks
from services.kb.chunking import chunk_markdown
from services.kb.domain import (
    KB_SOURCE_MANUAL,
    KB_SOURCE_UPLOAD,
    KB_SOURCE_URL,
    KB_STATUS_ERROR,
    KB_STATUS_PROCESSING,
    KB_STATUS_READY,
)
from services.kb.utils import (
    compute_markdown_hash,
    convert_html_to_markdown,
    document_origin_ref,
    fetch_url,
    get_revision_markdown,
    require_kb_workspace_id,
    truncate_markdown,
)
from services.kb.write_policy import (
    KBProvenance,
    enforce_kb_write_policy,
    lock_and_find_kb_duplicate,
)


async def ingest_kb_document(
    db: AsyncSession,
    *,
    document_id: UUID,
    workspace_id: UUID | None,
    initiated_by_user_id: UUID | None,
    annotation_model: Model | None = None,
) -> None:
    """Replace one document's chunks and queue additive embeddings."""
    workspace_id = require_kb_workspace_id(workspace_id)
    document = await _load_live_document(
        db,
        document_id=document_id,
        workspace_id=workspace_id,
    )
    if document is None:
        return

    document.status = KB_STATUS_PROCESSING
    document.processing_attempts = (document.processing_attempts or 0) + 1
    document.processing_error = None
    await db.commit()

    try:
        markdown = await _load_markdown(db, document)
        content_hash = compute_markdown_hash(markdown)
        duplicate = await lock_and_find_kb_duplicate(
            db,
            workspace_id=document.workspace_id,
            content_hash=content_hash,
            is_private=document.is_private,
            existing_id=document.id,
        )
        enforce_kb_write_policy(
            workspace_id=document.workspace_id,
            provenance=KBProvenance(
                actor_kind="system",
                source_type=document.source_type,
                origin_ref=document_origin_ref(document),
            ),
            title=document.title,
            content_md=markdown,
            is_private=document.is_private,
            existing=document,
            duplicate=duplicate,
        )
        if content_hash == document.content_hash and document.chunk_count > 0:
            document.status = KB_STATUS_READY
            document.processing_error = None
            await db.flush()
            return

        content_changed = content_hash != document.content_hash
        document.content_md = markdown
        document.content_hash = content_hash
        if content_changed:
            document.source_updated_at = datetime.now(UTC)
        # Publish the guarded hash and release its advisory lock before annotation work.
        await db.commit()
        await db.execute(delete(KBChunk).where(KBChunk.document_id == document.id))

        drafts = chunk_markdown(
            markdown,
            target_tokens=settings.KB_CHUNK_TARGET_TOKENS,
            max_tokens=settings.KB_CHUNK_MAX_TOKENS,
            overlap_tokens=settings.KB_CHUNK_OVERLAP_TOKENS,
        )
        chunks = [
            KBChunk(
                document_id=document.id,
                workspace_id=document.workspace_id,
                chunk_index=draft.chunk_index,
                content=draft.content,
                char_start=draft.char_start,
                char_end=draft.char_end,
                token_estimate=draft.token_estimate,
                meta={"headings": list(draft.heading_path)},
            )
            for draft in drafts
        ]
        db.add_all(chunks)
        document.chunk_count = len(chunks)
        await db.flush()

        if document.annotation_enabled:
            await annotate_chunks(
                db,
                document=document,
                chunks=chunks,
                model=annotation_model,
            )

        document.status = KB_STATUS_READY
        document.processing_error = None
        from services.jobs.enqueue_job import enqueue_job

        await enqueue_job(
            db,
            kind="kb.embed_chunks",
            workspace_id=document.workspace_id,
            subject_type="kb_document",
            subject_id=document.id,
            initiated_by_user_id=initiated_by_user_id,
        )
    except Exception as exc:
        await db.rollback()
        failed_document = await db.scalar(
            select(KBDocument).where(
                KBDocument.id == document_id,
                KBDocument.workspace_id == workspace_id,
            )
        )
        if failed_document is not None and not failed_document.deleted:
            failed_document.status = KB_STATUS_ERROR
            failed_document.processing_error = sanitize_error_message(
                str(exc) or exc.__class__.__name__
            )
            await db.commit()
        raise


async def _load_live_document(
    db: AsyncSession,
    *,
    document_id: UUID,
    workspace_id: UUID,
) -> KBDocument | None:
    return await db.scalar(
        select(KBDocument).where(
            KBDocument.id == document_id,
            KBDocument.workspace_id == workspace_id,
            KBDocument.deleted.is_(False),
        )
    )


async def _load_markdown(db: AsyncSession, document: KBDocument) -> str:
    if document.source_type == KB_SOURCE_MANUAL:
        markdown = document.content_md or ""
    elif document.source_type == KB_SOURCE_URL:
        if not document.external_url:
            raise AppValidationError("URL document has no source URL")
        data, content_type = await fetch_url(document.external_url)
        markdown = await convert_html_to_markdown(
            data,
            content_type=content_type,
            source_url=document.external_url,
        )
    elif document.source_type == KB_SOURCE_UPLOAD:
        if document.file_revision_id is None:
            raise AppValidationError("Upload document has no file revision")
        markdown = await get_revision_markdown(db, document.file_revision_id)
    else:
        raise AppValidationError("Knowledge-base source producer is not available")

    canonical = truncate_markdown(
        markdown,
        max_bytes=settings.KB_MAX_DOCUMENT_BYTES,
    )
    if not canonical.strip():
        raise AppValidationError("Knowledge-base document contains no readable content")
    return canonical
