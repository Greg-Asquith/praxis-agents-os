# apps/api/services/kb/create_document.py

"""Create a knowledge-base document and enqueue ingestion."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.files import FileRevision
from models.kb import KBDocument
from services.kb.domain import (
    ANNOTATION_DEFAULTS,
    KB_SOURCE_CONVERSATION,
    KB_SOURCE_INTEGRATION,
    KB_SOURCE_MANUAL,
    KB_SOURCE_UPLOAD,
    KB_SOURCE_URL,
    KB_SYNC_PENDING,
)
from services.kb.ensure_sweep_job import ensure_kb_sweep_job
from services.kb.utils import compute_markdown_hash, validate_source_url
from services.kb.write_policy import (
    KBProvenance,
    enforce_kb_write_policy,
    lock_and_find_kb_duplicate,
)

_INTEGRATION_META_KEYS = frozenset(
    {
        "provider_key",
        "source_title",
        "last_source_updated_at",
        "last_error_code",
    }
)


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
    external_id: str | None = None,
    integration_resource_id: UUID | None = None,
    is_private: bool = False,
    annotate: bool | None = None,
    meta: dict[str, Any] | None = None,
    provenance: KBProvenance | None = None,
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
    canonical_content: str | None = None
    content_hash = ""
    external_url: str | None = None
    source_updated_at = None
    document_meta = dict(meta or {})

    if source_type == KB_SOURCE_MANUAL:
        if content is None or not content.strip():
            raise AppValidationError("Manual documents require content", field="content")
        canonical_content = content
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
    elif source_type == KB_SOURCE_INTEGRATION:
        external_id = _require_integration_external_id(external_id)
        if integration_resource_id is None:
            raise AppValidationError(
                "Integration documents require a source resource",
                field="integration_resource_id",
            )
        if created_by_user_id is None:
            raise AppValidationError(
                "Integration documents require a creating user",
                field="created_by_user_id",
            )
        if url is None or not url.strip():
            raise AppValidationError(
                "Integration documents require a source URL",
                field="url",
            )
        external_url = url.strip()
        document_meta = _validate_integration_meta(document_meta)

    if source_type != KB_SOURCE_INTEGRATION and (
        external_id is not None or integration_resource_id is not None
    ):
        raise AppValidationError(
            "Integration source bindings require an integration document",
            field="integration_resource_id",
        )

    effective_provenance = provenance or KBProvenance(
        actor_kind="user" if created_by_user_id else "system",
        user_id=created_by_user_id,
        source_type=source_type,
        origin_ref=external_url or (str(file_revision_id) if file_revision_id else None),
    )
    duplicate = None
    if content_hash:
        duplicate = await lock_and_find_kb_duplicate(
            db,
            workspace_id=workspace_id,
            content_hash=content_hash,
            is_private=is_private,
        )
    enforce_kb_write_policy(
        workspace_id=workspace_id,
        provenance=effective_provenance,
        title=normalized_title,
        content_md=canonical_content,
        is_private=is_private,
        duplicate=duplicate,
    )

    document = KBDocument(
        workspace_id=workspace_id,
        title=normalized_title,
        source_type=source_type,
        source_updated_at=source_updated_at,
        content_hash=content_hash,
        content_md=canonical_content,
        file_revision_id=file_revision_id,
        integration_resource_id=integration_resource_id,
        external_id=external_id,
        external_url=external_url,
        source_sync_status=(KB_SYNC_PENDING if source_type == KB_SOURCE_INTEGRATION else None),
        is_private=is_private,
        created_by_user_id=created_by_user_id,
        annotation_enabled=ANNOTATION_DEFAULTS[source_type] if annotate is None else annotate,
        meta=document_meta,
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


def _require_integration_external_id(external_id: str | None) -> str:
    if external_id is None or not external_id.strip():
        raise AppValidationError(
            "Integration documents require an external source ID",
            field="external_id",
        )
    normalized = external_id.strip()
    if len(normalized) > 255:
        raise AppValidationError(
            "Integration source ID must be 255 characters or fewer",
            field="external_id",
        )
    return normalized


def _validate_integration_meta(meta: dict[str, Any]) -> dict[str, Any]:
    if set(meta).difference(_INTEGRATION_META_KEYS):
        raise AppValidationError(
            "Integration document metadata contains unsupported fields",
            field="meta",
        )
    provider_key = meta.get("provider_key")
    source_title = meta.get("source_title")
    if not isinstance(provider_key, str) or not provider_key.strip():
        raise AppValidationError(
            "Integration documents require a provider key",
            field="meta",
        )
    if not isinstance(source_title, str) or not source_title.strip():
        raise AppValidationError(
            "Integration documents require a source title",
            field="meta",
        )
    normalized = dict(meta)
    normalized["provider_key"] = provider_key.strip()[:64]
    normalized["source_title"] = source_title.strip()[:500]
    return normalized


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
