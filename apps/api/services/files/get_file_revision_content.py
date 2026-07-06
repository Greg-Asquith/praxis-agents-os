# apps/api/services/files/get_file_revision_content.py

"""Fetch editable text content for one immutable file revision."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, NotFoundError
from models.files import FileRevision
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.files.contract import is_editable
from services.files.domain import FileRevisionContentRead
from services.files.utils import get_file_for_workspace, private_ref_from_key
from services.storage.factory import get_storage_provider


async def get_file_revision_content(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    file_id: UUID,
    revision_id: UUID,
) -> FileRevisionContentRead:
    """Return stored UTF-8 text for one editable file revision."""
    file = await get_file_for_workspace(db, workspace=workspace, file_id=file_id)
    revision = await db.scalar(
        select(FileRevision).where(
            FileRevision.id == revision_id,
            FileRevision.file_id == file.id,
            FileRevision.workspace_id == workspace.id,
        )
    )
    if revision is None:
        raise NotFoundError(
            "File revision not found",
            resource_type="file_revision",
            resource_id=str(revision_id),
        )
    if not is_editable(revision.content_type):
        raise AppValidationError(
            "File revision does not support text content reads",
            field="revision_id",
            details={"content_type": revision.content_type},
        )

    data = await get_storage_provider().get_object(private_ref_from_key(revision.object_key))
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.READ,
        resource_type=AuditResourceType.FILE,
        resource_id=file.id,
        actor=actor,
        details={"filename": file.name, "revision_id": str(revision.id), "source": "content"},
    )
    return FileRevisionContentRead(
        file_id=file.id,
        revision_id=revision.id,
        revision_number=revision.revision_number,
        content_type=revision.content_type,
        size_bytes=revision.size_bytes,
        content_hash=revision.content_hash,
        content=data.decode("utf-8", errors="replace"),
    )
