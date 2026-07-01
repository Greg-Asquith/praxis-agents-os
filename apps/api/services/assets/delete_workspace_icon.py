# apps/api/services/assets/delete_workspace_icon.py

"""Delete a workspace's managed icon."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.assets.utils import best_effort_delete_public_object
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.storage.factory import get_storage_provider
from services.workspaces.schemas import WorkspaceRead
from services.workspaces.utils import MANAGER_ROLES, require_workspace_role


async def delete_workspace_icon(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace_id: UUID,
) -> WorkspaceRead:
    workspace, membership = await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace_id,
        allowed_roles=MANAGER_ROLES,
    )
    previous_object_key = workspace.icon_object_key
    provider = get_storage_provider()

    if workspace.icon_url is not None or workspace.icon_object_key is not None:
        workspace.icon_url = None
        workspace.icon_object_key = None
        await db.flush()
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace.id,
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.WORKSPACE,
            resource_id=workspace.id,
            actor=actor,
            details={
                "fields": ["icon_url", "icon_object_key"],
                "storage_provider": provider.provider_key,
            },
        )
        await db.refresh(workspace)

    if previous_object_key:
        await best_effort_delete_public_object(previous_object_key, provider=provider)

    return WorkspaceRead.from_workspace(workspace, current_user_role=membership.role)
