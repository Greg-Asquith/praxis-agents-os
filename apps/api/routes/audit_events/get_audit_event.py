# apps/api/routes/audit_events/get_audit_event.py

"""Route for reading a workspace audit event."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.audit_events import get_audit_event_for_workspace
from services.audit_events.schemas import AuditEventRead

router = APIRouter()


@router.get("/{event_id}")
async def get_audit_event(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    event_id: Annotated[UUID, Path()],
) -> AuditEventRead:
    workspace, _membership = workspace_context
    return await get_audit_event_for_workspace(db, workspace=workspace, event_id=event_id)
