# apps/api/services/files/delete_file.py

"""Soft-delete a workspace file."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.files.utils import get_file_for_workspace, require_file_write_access


async def delete_file(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    file_id: UUID,
) -> None:
    """Soft-delete a file while leaving its blobs in retention."""
    require_file_write_access(membership)
    file = await get_file_for_workspace(
        db,
        workspace=workspace,
        file_id=file_id,
        for_update=True,
    )
    file.soft_delete(deleted_by=actor.id)
    await db.flush()
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.FILE,
        resource_id=file.id,
        actor=actor,
        details={"filename": file.name},
    )
