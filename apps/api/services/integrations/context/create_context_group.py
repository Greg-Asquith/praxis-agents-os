# apps/api/services/integrations/context/create_context_group.py

"""Create a workspace integration context group."""

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.integration_context import IntegrationContextGroup, IntegrationContextGroupMember
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditResourceType, record_workspace_audit_event
from services.integrations.context.schemas import ContextGroupCreateRequest, ContextGroupRead
from services.integrations.context.utils import (
    context_group_conflict,
    load_workspace_resources,
    normalize_context_group_name,
    reload_group_read,
)


async def create_context_group(
    db: AsyncSession,
    *,
    request: Request | None,
    actor: User,
    workspace: Workspace,
    payload: ContextGroupCreateRequest,
) -> ContextGroupRead:
    name = normalize_context_group_name(payload.name)
    resources = await load_workspace_resources(
        db,
        resource_ids=payload.resource_ids,
        actor=actor,
        workspace=workspace,
    )
    group = IntegrationContextGroup(
        workspace_id=workspace.id,
        name=name,
        created_by_user_id=actor.id,
        members=[
            IntegrationContextGroupMember(integration_resource_id=resource.id)
            for resource in resources
        ],
    )
    try:
        async with db.begin_nested():
            db.add(group)
            await db.flush()
    except IntegrityError as exc:
        conflict = context_group_conflict(exc)
        if conflict is not None:
            raise conflict from exc
        raise

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.INTEGRATION_CONTEXT_GROUP,
        resource_id=group.id,
        actor=actor,
        details={"name": group.name, "resource_ids": [resource.id for resource in resources]},
    )
    return await reload_group_read(db, group_id=group.id, workspace=workspace)
