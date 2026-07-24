# apps/api/services/kb/create_document.py

"""Create a knowledge-base document and enqueue ingestion."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.files import FileRevision
from models.kb import KBDocument
from services.kb.domain import (
    ANNOTATION_DEFAULTS,
    KB_SOURCE_CONVERSATION,
    KB_SOURCE_INTEGRATION,
    KB_SOURCE_MANUAL,
    KB_SOURCE_UPLOAD,
    KB_SOURCE_URL,
)
from services.kb.ensure_sweep_job import ensure_kb_sweep_job
from services.kb.utils import compute_markdown_hash, truncate_markdown, validate_source_url


async def create_kb_document(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    source_type: str,
    title: str,
    created_by_user_id: UUID | None = None,
    content: str | None = None,
    url: str | None = None,
    file_revision_id: UUID | None = None,
    is_private: bool = False,
    annotate: bool | None = None,
    meta: dict[str, Any] | None = None,
) -> KBDocument:
    """Persist one private workspace document and queue its ingestion."""
    normalized_title = title.strip()
    if not normalized_title:
        raise AppValidationError("Document title is required", field="title")

    if source_type not in ANNOTATION_DEFAULTS:
        raise AppValidationError("Knowledge-base source type is invalid", field="source_type")
    if source_type == KB_SOURCE_CONVERSATION:
        raise AppValidationError(
            "Conversation knowledge sources are pending the document-source workflow",
            field="source_type",
            details={"planned_owner": "knowledge document sources"},
        )
    if source_type == KB_SOURCE_INTEGRATION:
        raise AppValidationError(
            "Integration knowledge sources are pending provider source support",
            field="source_type",
            details={"planned_owner": "integration knowledge sources"},
        )

    canonical_content: str | None = None
    content_hash = ""
    external_url: str | None = None
    source_updated_at = None

    if source_type == KB_SOURCE_MANUAL:
        if content is None or not content.strip():
            raise AppValidationError("Manual documents require content", field="content")
        canonical_content = truncate_markdown(
            content,
            max_bytes=settings.KB_MAX_DOCUMENT_BYTES,
        )
        content_hash = compute_markdown_hash(canonical_content)
        source_updated_at = datetime.now(UTC)
    elif source_type == KB_SOURCE_URL:
        external_url = validate_source_url(url)
    elif source_type == KB_SOURCE_UPLOAD:
        await _validate_file_revision(
            db,
            workspace_id=workspace_id,
            file_revision_id=file_revision_id,
        )

    document = KBDocument(
        workspace_id=workspace_id,
        title=normalized_title,
        source_type=source_type,
        source_updated_at=source_updated_at,
        content_hash=content_hash,
        content_md=canonical_content,
        file_revision_id=file_revision_id,
        external_url=external_url,
        is_private=is_private,
        created_by_user_id=created_by_user_id,
        annotation_enabled=ANNOTATION_DEFAULTS[source_type] if annotate is None else annotate,
        meta=dict(meta or {}),
    )
    db.add(document)
    await db.flush()

    from services.jobs.enqueue_job import enqueue_job

    await enqueue_job(
        db,
        kind="kb.ingest_document",
        workspace_id=workspace_id,
        subject_type="kb_document",
        subject_id=document.id,
        initiated_by_user_id=created_by_user_id,
    )
    await ensure_kb_sweep_job(db)
    return document


async def _validate_file_revision(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    file_revision_id: UUID | None,
) -> None:
    if file_revision_id is None:
        raise AppValidationError(
            "Upload documents require a file revision",
            field="file_revision_id",
        )
    revision_id = await db.scalar(
        select(FileRevision.id).where(
            FileRevision.id == file_revision_id,
            FileRevision.workspace_id == workspace_id,
        )
    )
    if revision_id is None:
        raise AppValidationError(
            "File revision does not exist in this workspace",
            field="file_revision_id",
        )
