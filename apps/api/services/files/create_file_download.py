# apps/api/services/files/create_file_download.py

"""Create a signed download grant for a workspace file."""

from datetime import timedelta
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.files.domain import FileDownloadGrant, FileDownloadRequest
from services.files.utils import file_revision_ref, get_visible_file, get_visible_file_revision
from services.storage.factory import get_storage_provider


async def create_file_download(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    file_id: UUID,
    payload: FileDownloadRequest,
) -> FileDownloadGrant:
    """Create a short-lived signed download for the current or selected revision."""
    file = await get_visible_file(db, workspace_id=workspace.id, file_id=file_id)
    revision_id = payload.revision_id
    revision = await get_visible_file_revision(
        db, workspace_id=workspace.id, file=file, revision_id=revision_id
    )

    provider = get_storage_provider()
    download = await provider.create_signed_download(
        file_revision_ref(revision),
        expires_in=timedelta(minutes=10),
        force_download=payload.force_download,
        filename=file.name,
    )
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.READ,
        resource_type=AuditResourceType.FILE,
        resource_id=file.id,
        actor=actor,
        details={"filename": file.name, "revision_id": str(revision.id)},
    )
    return FileDownloadGrant(download=download, expires_at=download.expires_at)
