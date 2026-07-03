# apps/api/services/security/list_events.py

"""List security events."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from services.security.enums import SecurityEventType
from services.security.queries import (
    count_security_events,
    list_security_events as query_security_events,
)
from services.security.schemas import SecurityEventRead, SecurityEventsListResponse


async def list_security_events_for_super_admin(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    event_type: str | None = None,
    ip_address: str | None = None,
    user_email: str | None = None,
    endpoint: str | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
) -> SecurityEventsListResponse:
    """Return a paginated security-event envelope for super-admin views."""
    parsed_event_type = _parse_enum(event_type, SecurityEventType, field="event_type")

    events = await query_security_events(
        db,
        event_type=parsed_event_type,
        ip_address=ip_address,
        user_email=user_email,
        endpoint=endpoint,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
        limit=limit,
        offset=offset,
    )
    total = await count_security_events(
        db,
        event_type=parsed_event_type,
        ip_address=ip_address,
        user_email=user_email,
        endpoint=endpoint,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
    )

    return SecurityEventsListResponse(
        events=[SecurityEventRead.from_event(event) for event in events],
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
