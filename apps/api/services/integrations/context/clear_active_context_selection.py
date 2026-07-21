# apps/api/services/integrations/context/clear_active_context_selection.py

"""Clear one conversation's active integration context selection."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.integration_context import ActiveContextSelection
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditResourceType, record_workspace_audit_event
from services.conversations.utils import get_conversation_for_actor


async def clear_active_context_selection(
    db: AsyncSession,
    *,
    request: Request | None,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
) -> None:
    conversation = await get_conversation_for_actor(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    result = await db.execute(
        delete(ActiveContextSelection)
        .where(
            ActiveContextSelection.conversation_id == conversation.id,
            ActiveContextSelection.workspace_id == workspace.id,
        )
        .returning(ActiveContextSelection.id)
    )
    selection_id = result.scalar_one_or_none()
    if selection_id is None:
        return
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.ACTIVE_CONTEXT_SELECTION,
        resource_id=selection_id,
        actor=actor,
        details={"conversation_id": conversation.id},
    )
