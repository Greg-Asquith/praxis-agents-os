# apps/api/services/integrations/context/update_context_group.py

"""Update a workspace integration context group."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.integration_context import IntegrationContextGroupMember
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditResourceType, record_workspace_audit_event
from services.integrations.context.schemas import ContextGroupRead, ContextGroupUpdateRequest
from services.integrations.context.utils import (
    context_group_conflict,
    load_workspace_group,
    load_workspace_resources,
    normalize_context_group_name,
    reload_group_read,
)


async def update_context_group(
    db: AsyncSession,
    *,
    request: Request | None,
    actor: User,
    workspace: Workspace,
    group_id: UUID,
    payload: ContextGroupUpdateRequest,
) -> ContextGroupRead:
    group = await load_workspace_group(
        db,
        group_id=group_id,
        workspace=workspace,
        for_update=True,
    )
    changed_fields: list[str] = []
    resources = None
    if "name" in payload.model_fields_set:
        if payload.name is None:
            from core.exceptions.general import AppValidationError

            raise AppValidationError("Context group name cannot be null", field="name")
        name = normalize_context_group_name(payload.name)
        if group.name != name:
            group.name = name
            changed_fields.append("name")
    if "resource_ids" in payload.model_fields_set:
        if payload.resource_ids is None:
            from core.exceptions.general import AppValidationError

            raise AppValidationError("Context group resources cannot be null", field="resource_ids")
        resources = await load_workspace_resources(
            db,
            resource_ids=payload.resource_ids,
            workspace=workspace,
        )
        current_ids = {member.integration_resource_id for member in group.members}
        next_ids = {resource.id for resource in resources}
        if current_ids != next_ids:
            group.members = [
                IntegrationContextGroupMember(integration_resource_id=resource.id)
                for resource in resources
            ]
            changed_fields.append("resource_ids")

    if changed_fields:
        try:
            async with db.begin_nested():
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
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.INTEGRATION_CONTEXT_GROUP,
            resource_id=group.id,
            actor=actor,
            details={"changed_fields": changed_fields},
        )
    return await reload_group_read(db, group_id=group.id, workspace=workspace)
