# apps/api/services/security/get_event.py

"""Read a security event."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from services.security.queries import get_security_event as query_security_event
from services.security.schemas import SecurityEventRead


async def get_security_event_for_super_admin(
    db: AsyncSession,
    *,
    event_id: UUID,
) -> SecurityEventRead:
    event = await query_security_event(db, event_id=event_id)
    if event is None:
        raise NotFoundError(
            "Security event not found",
            resource_type="security_event",
            resource_id=str(event_id),
        )

    return SecurityEventRead.from_event(event)
