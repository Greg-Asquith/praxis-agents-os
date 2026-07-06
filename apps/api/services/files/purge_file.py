# apps/api/services/files/purge_file.py

"""Hard-delete a workspace file and its stored objects."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.files import FileRevision
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.files.utils import (
    best_effort_delete_file_object,
    distinct_object_keys,
    get_file_for_workspace,
    require_file_purge_access,
)
from services.storage.factory import get_storage_provider


async def purge_file(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    file_id: UUID,
) -> None:
    """Permanently remove a file row and every distinct revision object."""
    require_file_purge_access(membership)
    file = await get_file_for_workspace(
        db,
        workspace=workspace,
        file_id=file_id,
        include_deleted=True,
        for_update=True,
    )
    revisions = (
        await db.scalars(
            select(FileRevision).where(
                FileRevision.file_id == file.id,
                FileRevision.workspace_id == workspace.id,
            )
        )
    ).all()
    provider = get_storage_provider()
    for object_key in distinct_object_keys(list(revisions)):
        await best_effort_delete_file_object(object_key, provider=provider)

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.FILE,
        resource_id=file.id,
        actor=actor,
        details={"filename": file.name, "purge": True},
    )
    await db.delete(file)
    await db.flush()
