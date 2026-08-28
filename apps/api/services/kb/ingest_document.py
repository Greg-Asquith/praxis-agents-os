# apps/api/services/kb/ingest_document.py

"""Ingest one knowledge-base document into lexical chunks."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic_ai.models import Model
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.exceptions.integration import IntegrationRateLimitError, IntegrationTimeoutError
from core.settings import settings
from models.kb import KBChunk, KBDocument
from services.integrations.plugin import (
    KnowledgeSourceAccessLostError,
    KnowledgeSourceDisconnectedError,
    KnowledgeSourceDocument,
)
from services.jobs.utils import sanitize_error_message
from services.kb.annotation import annotate_chunks
from services.kb.chunking import chunk_markdown
from services.kb.domain import (
    KB_SOURCE_INTEGRATION,
    KB_SOURCE_MANUAL,
    KB_SOURCE_UPLOAD,
    KB_SOURCE_URL,
    KB_STATUS_ERROR,
    KB_STATUS_PROCESSING,
    KB_STATUS_READY,
    KB_SYNC_DISCONNECTED,
    KB_SYNC_ERROR,
    KB_SYNC_READY,
    KB_SYNC_UNAVAILABLE,
)
from services.kb.integration_sources.fetch import fetch_integration_source
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
        loaded = await _load_markdown(db, document)
        markdown = loaded.markdown
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
            _apply_integration_source_success(document, loaded.source_document)
            document.status = KB_STATUS_READY
            document.processing_error = None
            await db.flush()
            return

        content_changed = content_hash != document.content_hash
        document.content_md = markdown
        document.content_hash = content_hash
        document.chunk_count = 0
        if loaded.source_document is None and content_changed:
            document.source_updated_at = datetime.now(UTC)
        # Publish an incomplete materialization and release its advisory lock before annotation.
        await db.execute(delete(KBChunk).where(KBChunk.document_id == document.id))
        await db.commit()

        drafts = chunk_markdown(
            markdown,
            target_tokens=settings.KB_CHUNK_TARGET_TOKENS,
            max_tokens=settings.KB_CHUNK_MAX_TOKENS,
            overlap_tokens=settings.KB_CHUNK_OVERLAP_TOKENS,
        )
        # Pure-markup fragments would outrank real content, so they are never indexed.
        drafts = [draft for draft in drafts if any(char.isalnum() for char in draft.content)]
        chunks = [
            KBChunk(
                document_id=document.id,
                workspace_id=document.workspace_id,
                chunk_index=chunk_index,
                content=draft.content,
                char_start=draft.char_start,
                char_end=draft.char_end,
                token_estimate=draft.token_estimate,
                meta={"headings": list(draft.heading_path)},
            )
            for chunk_index, draft in enumerate(drafts)
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

        _apply_integration_source_success(document, loaded.source_document)
        document.status = KB_STATUS_READY
        document.processing_error = None
        await db.flush()
        from services.jobs.enqueue_job import enqueue_job

        await enqueue_job(
            db,
            kind="kb.embed_chunks",
            workspace_id=document.workspace_id,
            subject_type="kb_document",
            subject_id=document.id,
            initiated_by_user_id=initiated_by_user_id,
        )
    except KnowledgeSourceAccessLostError:
        await _record_definitive_source_failure(
            db,
            document_id=document_id,
            workspace_id=workspace_id,
            sync_status=KB_SYNC_UNAVAILABLE,
            error_code="access_lost",
            message="This source is no longer accessible through its connected account.",
        )
    except KnowledgeSourceDisconnectedError:
        await _record_definitive_source_failure(
            db,
            document_id=document_id,
            workspace_id=workspace_id,
            sync_status=KB_SYNC_DISCONNECTED,
            error_code="disconnected",
            message="The connection for this source is no longer available.",
        )
    except Exception as exc:
        await db.rollback()
        failed_document = await _load_live_document(
            db,
            document_id=document_id,
            workspace_id=workspace_id,
        )
        if failed_document is not None and not failed_document.deleted:
            failed_document.status = KB_STATUS_ERROR
            failed_document.processing_error = sanitize_error_message(
                str(exc) or exc.__class__.__name__
            )
            if failed_document.source_type == KB_SOURCE_INTEGRATION:
                failed_document.source_sync_status = KB_SYNC_ERROR
                failed_document.source_synced_at = datetime.now(UTC)
                failed_document.meta = _integration_meta_with_error(
                    failed_document,
                    error_code=_transient_source_error_code(exc),
                )
            await db.commit()
        raise


async def _record_definitive_source_failure(
    db: AsyncSession,
    *,
    document_id: UUID,
    workspace_id: UUID,
    sync_status: str,
    error_code: str,
    message: str,
) -> None:
    await db.rollback()
    failed_document = await _load_live_document(
        db,
        document_id=document_id,
        workspace_id=workspace_id,
    )
    if failed_document is None:
        await db.rollback()
        return

    failed_document.source_sync_status = sync_status
    failed_document.source_synced_at = datetime.now(UTC)
    failed_document.content_md = None
    failed_document.summary = None
    failed_document.content_hash = ""
    failed_document.chunk_count = 0
    failed_document.status = KB_STATUS_ERROR
    failed_document.processing_error = message
    failed_document.meta = _integration_meta_with_error(
        failed_document,
        error_code=error_code,
    )
    await db.execute(delete(KBChunk).where(KBChunk.document_id == failed_document.id))
    await db.commit()


def _integration_meta_with_error(
    document: KBDocument,
    *,
    error_code: str,
) -> dict[str, object]:
    meta = {
        key: document.meta[key]
        for key in ("provider_key", "source_title", "last_source_updated_at")
        if key in document.meta
    }
    meta["last_error_code"] = error_code
    return meta


def _transient_source_error_code(exc: Exception) -> str:
    if isinstance(exc, IntegrationRateLimitError):
        return "rate_limited"
    if isinstance(exc, (IntegrationTimeoutError, TimeoutError)):
        return "timeout"
    return "refresh_failed"


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


async def _load_markdown(db: AsyncSession, document: KBDocument) -> "_LoadedMarkdown":
    source_document = None
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
    elif document.source_type == KB_SOURCE_INTEGRATION:
        source_document = await fetch_integration_source(document)
        markdown = source_document.markdown
    else:
        raise AppValidationError("Knowledge-base source producer is not available")

    canonical = truncate_markdown(
        markdown,
        max_bytes=settings.KB_MAX_DOCUMENT_BYTES,
    )
    if not canonical.strip():
        raise AppValidationError("Knowledge-base document contains no readable content")
    return _LoadedMarkdown(markdown=canonical, source_document=source_document)


@dataclass(frozen=True)
class _LoadedMarkdown:
    markdown: str
    source_document: KnowledgeSourceDocument | None


def _apply_integration_source_success(
    document: KBDocument,
    source_document: KnowledgeSourceDocument | None,
) -> None:
    if source_document is None:
        return
    synced_at = datetime.now(UTC)
    document.external_id = source_document.external_id
    document.external_url = source_document.url
    document.source_updated_at = source_document.source_updated_at
    document.source_sync_status = KB_SYNC_READY
    document.source_synced_at = synced_at
    document.meta = {
        "provider_key": document.meta.get("provider_key"),
        "source_title": source_document.title[:500],
        "last_source_updated_at": (
            source_document.source_updated_at.isoformat()
            if source_document.source_updated_at is not None
            else None
        ),
    }
