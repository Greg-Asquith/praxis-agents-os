# apps/api/services/security/events.py

"""Security-event writers."""

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_async_db_session_factory
from models.security import SecurityEvent
from services.security.enums import SecurityEventType
from utils.json_safe import json_safe_details

logger = logging.getLogger(__name__)


async def _record_security_event(
    db: AsyncSession,
    *,
    event_type: SecurityEventType,
    ip_address: str,
    endpoint: str | None = None,
    user_email: str | None = None,
    user_agent: str | None = None,
    details: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    occurred_at: datetime | None = None,
) -> SecurityEvent:
    """Persist one security event using the caller-owned database session.

    Private: callers use :func:`safe_record_security_event` so a logging write
    failure can never roll back the request being protected.
    """

    event = SecurityEvent(
        occurred_at=occurred_at or datetime.now(UTC),
        event_type=event_type,
        ip_address=ip_address,
        endpoint=endpoint,
        user_email=user_email,
        user_agent=user_agent,
        details=json_safe_details(details or {}),
        request_id=request_id,
    )
    db.add(event)
    await db.flush()
    return event


async def safe_record_security_event(db: AsyncSession, **kwargs: Any) -> None:
    """Record a security event in a savepoint so a failure never rolls back the
    caller's work; the lost event is logged instead.

    This is the only supported way to write a security event: security logging
    must never stop the request it protects from completing.
    """
    try:
        async with db.begin_nested():
            await _record_security_event(db, **kwargs)
    except Exception:
        logger.error("Failed to record security event; request preserved", exc_info=True)


async def safe_record_security_event_committed(**kwargs: Any) -> None:
    """Record a security event in an independent committed transaction.

    Use this for auth/security failures that intentionally return a 4xx response:
    request-scoped database work is rolled back for those responses, but the
    security record still needs to survive.
    """
    try:
        session_factory = get_async_db_session_factory()
        async with session_factory() as db:
            await safe_record_security_event(db, **kwargs)
            await db.commit()
    except Exception:
        logger.error("Failed to record committed security event", exc_info=True)
