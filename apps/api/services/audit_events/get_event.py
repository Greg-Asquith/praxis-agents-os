# apps/api/services/audit_events/get_event.py

"""Read a workspace-scoped audit event."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.workspace import Workspace
from services.audit_events.queries import get_audit_event as query_audit_event
from services.audit_events.schemas import AuditEventRead


async def get_audit_event_for_workspace(
    db: AsyncSession,
    *,
    workspace: Workspace,
    event_id: UUID,
) -> AuditEventRead:
    event = await query_audit_event(db, event_id=event_id, workspace_id=workspace.id)
    if event is None:
        raise NotFoundError(
            "Audit event not found",
            resource_type="audit_event",
            resource_id=str(event_id),
        )

    return AuditEventRead.from_event(event)
