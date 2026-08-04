# apps/api/services/integrations/context/clear_active_context_selection.py

"""Clear one conversation's active integration context selection."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation import Conversation
from models.integration_context import ActiveContextSelection
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditResourceType, record_workspace_audit_event
from services.workspaces.utils import READ_ROLES, require_workspace_role


async def clear_active_context_selection(
    db: AsyncSession,
    *,
    request: Request | None,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
) -> None:
    await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace.id,
        allowed_roles=READ_ROLES,
    )

    # Import lazily so loading the agent runtime does not pull its streaming worker
    # back in through the conversations package while execute_run is initializing.
    from services.conversations.utils import get_conversation_for_actor

    conversation = await get_conversation_for_actor(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    await db.execute(
        select(Conversation.id).where(Conversation.id == conversation.id).with_for_update()
    )
    deleted = (
        await db.execute(
            delete(ActiveContextSelection)
            .where(
                ActiveContextSelection.conversation_id == conversation.id,
                ActiveContextSelection.workspace_id == workspace.id,
            )
            .returning(
                ActiveContextSelection.integration_resource_id,
                ActiveContextSelection.context_group_id,
            )
        )
    ).all()
    if not deleted:
        return
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.ACTIVE_CONTEXT_SELECTION,
        resource_id=conversation.id,
        actor=actor,
        details={
            "conversation_id": conversation.id,
            "targets": [
                (
                    {"type": "resource", "integration_resource_id": str(resource_id)}
                    if resource_id is not None
                    else {"type": "context_group", "context_group_id": str(group_id)}
                )
                for resource_id, group_id in deleted
            ],
        },
    )
