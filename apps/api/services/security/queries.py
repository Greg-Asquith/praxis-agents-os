# apps/api/services/security/queries.py

"""Read access to the security-event log for routes to call later."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.security import SecurityEvent
from services.security.enums import SecurityEventType
from utils.pagination import paginate


def _filtered_select(
    base,
    *,
    event_type: SecurityEventType | None,
    ip_address: str | None,
    user_email: str | None,
    endpoint: str | None,
    occurred_after: datetime | None,
    occurred_before: datetime | None,
):
    """Apply the shared security-log filters to a select() statement."""
    if event_type is not None:
        base = base.where(SecurityEvent.event_type == event_type)
    if ip_address is not None:
        base = base.where(SecurityEvent.ip_address == ip_address)
    if user_email is not None:
        base = base.where(SecurityEvent.user_email == user_email)
    if endpoint is not None:
        base = base.where(SecurityEvent.endpoint == endpoint)
    if occurred_after is not None:
        base = base.where(SecurityEvent.occurred_at >= occurred_after)
    if occurred_before is not None:
        base = base.where(SecurityEvent.occurred_at < occurred_before)
    return base


async def list_security_events(
    db: AsyncSession,
    *,
    event_type: SecurityEventType | None = None,
    ip_address: str | None = None,
    user_email: str | None = None,
    endpoint: str | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[SecurityEvent]:
    """Return security events newest-first, narrowed by the given filters."""
    events, _total = await list_security_events_page(
        db,
        event_type=event_type,
        ip_address=ip_address,
        user_email=user_email,
        endpoint=endpoint,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
        limit=limit,
        offset=offset,
    )
    return events


async def list_security_events_page(
    db: AsyncSession,
    *,
    event_type: SecurityEventType | None = None,
    ip_address: str | None = None,
    user_email: str | None = None,
    endpoint: str | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SecurityEvent], int]:
    """Return security events and the total count for the same filters."""
    stmt = _filtered_select(
        select(SecurityEvent),
        event_type=event_type,
        ip_address=ip_address,
        user_email=user_email,
        endpoint=endpoint,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
    )
    return await paginate(db, stmt, SecurityEvent.occurred_at.desc(), limit=limit, offset=offset)


async def get_security_event(
    db: AsyncSession,
    *,
    event_id: UUID | str,
) -> SecurityEvent | None:
    """Fetch a single security event by id."""
    result = await db.execute(select(SecurityEvent).where(SecurityEvent.id == event_id))
    return result.scalar_one_or_none()
