# apps/api/services/integrations/context/set_active_context_selection.py

"""Atomically set one conversation's active integration context selection."""

from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.integration_context import ActiveContextSelection
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditResourceType, record_workspace_audit_event
from services.integrations.context.schemas import ActiveContextSelectionValue
from services.integrations.context.utils import load_selection_group, load_selection_resource
from services.workspaces.utils import READ_ROLES, require_workspace_role


async def set_active_context_selection(
    db: AsyncSession,
    *,
    request: Request | None,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
    selection: ActiveContextSelectionValue,
) -> ActiveContextSelection:
    """Validate and atomically upsert a selection without a read/insert race."""
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
    if selection.type == "resource":
        resource_id = selection.integration_resource_id
        if resource_id is None:  # pragma: no cover - enforced by the tagged schema
            raise RuntimeError("Resource selection has no resource target")
        await load_selection_resource(
            db,
            resource_id=resource_id,
            actor=actor,
            workspace=workspace,
        )
    else:
        group_id = selection.context_group_id
        if group_id is None:  # pragma: no cover - enforced by the tagged schema
            raise RuntimeError("Context group selection has no group target")
        await load_selection_group(
            db,
            group_id=group_id,
            workspace=workspace,
        )

    statement = (
        insert(ActiveContextSelection)
        .values(
            id=uuid4(),
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            integration_resource_id=selection.integration_resource_id,
            context_group_id=selection.context_group_id,
        )
        .on_conflict_do_update(
            constraint="uq_active_context_selections_conversation",
            set_={
                "integration_resource_id": selection.integration_resource_id,
                "context_group_id": selection.context_group_id,
                "updated_at": func.now(),
            },
        )
        .returning(ActiveContextSelection)
        .execution_options(populate_existing=True)
    )
    persisted = (await db.scalars(statement)).one()

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.ACTIVE_CONTEXT_SELECTION,
        resource_id=persisted.id,
        actor=actor,
        details={
            "selection_type": selection.type,
            "conversation_id": conversation.id,
            "integration_resource_id": selection.integration_resource_id,
            "context_group_id": selection.context_group_id,
        },
    )
    return persisted
