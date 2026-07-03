# apps/api/routes/security_events/list_security_events.py

"""Route for listing security events."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep
from services.security import list_security_events_for_super_admin
from services.security.schemas import SecurityEventsListResponse

router = APIRouter()


@router.get("/")
async def list_security_events(
    db: AsyncDbSessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    event_type: Annotated[str | None, Query(max_length=100)] = None,
    user_email: Annotated[str | None, Query(max_length=320)] = None,
    ip_address: Annotated[str | None, Query(max_length=64)] = None,
    endpoint: Annotated[str | None, Query(max_length=500)] = None,
    occurred_after: Annotated[datetime | None, Query()] = None,
    occurred_before: Annotated[datetime | None, Query()] = None,
) -> SecurityEventsListResponse:
    return await list_security_events_for_super_admin(
        db,
        limit=limit,
        offset=offset,
        event_type=event_type,
        user_email=user_email,
        ip_address=ip_address,
        endpoint=endpoint,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
    )
