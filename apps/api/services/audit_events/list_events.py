# apps/api/services/audit_events/list_events.py

"""List workspace-scoped audit events."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.workspace import Workspace
from services.audit_events.enums import AuditAction, AuditResourceType, AuditStatus
from services.audit_events.queries import list_audit_events_page
from services.audit_events.schemas import AuditEventRead, AuditEventsListResponse


async def list_audit_events_for_workspace(
    db: AsyncSession,
    *,
    workspace: Workspace,
    limit: int,
    offset: int,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    actor_user_id: UUID | None = None,
    status: str | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
) -> AuditEventsListResponse:
    """Return a paginated audit-event envelope for one workspace."""
    parsed_action = _parse_enum(action, AuditAction, field="action")
    parsed_resource_type = _parse_enum(
        resource_type,
        AuditResourceType,
        field="resource_type",
    )
    parsed_status = _parse_enum(status, AuditStatus, field="status")

    events, total = await list_audit_events_page(
        db,
        workspace_id=workspace.id,
        resource_type=parsed_resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        action=parsed_action,
        status=parsed_status,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
        limit=limit,
        offset=offset,
    )

    return AuditEventsListResponse(
        events=[AuditEventRead.from_event(event) for event in events],
        total=total,
        limit=limit,
        offset=offset,
    )


def _parse_enum[T: StrEnum](
    value: str | None,
    enum_type: type[T],
    *,
    field: str,
) -> T | None:
    if value is None:
        return None
    try:
        return enum_type(value)
    except ValueError as exc:
        raise AppValidationError(
            f"Invalid {field}",
            field=field,
            details={"allowed_values": [item.value for item in enum_type]},
        ) from exc
