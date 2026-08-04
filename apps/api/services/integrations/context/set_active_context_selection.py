# apps/api/services/integrations/context/set_active_context_selection.py

"""Atomically replace one conversation's active integration context targets."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation import Conversation
from models.integration_context import ActiveContextSelection
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditResourceType, record_workspace_audit_event
from services.integrations.context.schemas import ActiveContextTargets
from services.integrations.context.utils import validate_active_context_targets
from services.workspaces.utils import READ_ROLES, require_workspace_role


async def set_active_context_selection(
    db: AsyncSession,
    *,
    request: Request | None,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
    targets: ActiveContextTargets,
) -> list[ActiveContextSelection]:
    """Validate every target, then replace the set under a conversation row lock."""
    await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace.id,
        allowed_roles=READ_ROLES,
    )

    # Import lazily to avoid a cycle between runtime setup and conversation streaming.
    from services.conversations.utils import get_conversation_for_actor

    conversation = await get_conversation_for_actor(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    # Serializing replacements on their owning conversation prevents concurrent
    # delete/insert operations from combining two callers' target sets.
    await db.execute(
        select(Conversation.id).where(Conversation.id == conversation.id).with_for_update()
    )

    await validate_active_context_targets(
        db,
        targets=targets,
        actor=actor,
        workspace=workspace,
    )

    await db.execute(
        delete(ActiveContextSelection).where(
            ActiveContextSelection.conversation_id == conversation.id,
            ActiveContextSelection.workspace_id == workspace.id,
        )
    )
    persisted = [
        ActiveContextSelection(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            integration_resource_id=target.integration_resource_id,
            context_group_id=target.context_group_id,
        )
        for target in targets.targets
    ]
    db.add_all(persisted)
    await db.flush()

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.ACTIVE_CONTEXT_SELECTION,
        resource_id=conversation.id,
        actor=actor,
        details={
            "conversation_id": conversation.id,
            "targets": targets.model_dump(mode="json")["targets"],
        },
    )
    return persisted
