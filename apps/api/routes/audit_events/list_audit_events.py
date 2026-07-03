# apps/api/routes/audit_events/list_audit_events.py

"""Route for listing workspace audit events."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.audit_events import list_audit_events_for_workspace
from services.audit_events.schemas import AuditEventsListResponse

router = APIRouter()


@router.get("/")
async def list_audit_events(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    action: Annotated[str | None, Query(max_length=64)] = None,
    resource_type: Annotated[str | None, Query(max_length=100)] = None,
    resource_id: Annotated[str | None, Query(max_length=255)] = None,
    actor_user_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[str | None, Query(max_length=32)] = None,
    occurred_after: Annotated[datetime | None, Query()] = None,
    occurred_before: Annotated[datetime | None, Query()] = None,
) -> AuditEventsListResponse:
    workspace, _membership = workspace_context
    return await list_audit_events_for_workspace(
        db,
        workspace=workspace,
        limit=limit,
        offset=offset,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        status=status,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
    )
