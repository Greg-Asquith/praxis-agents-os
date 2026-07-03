# apps/api/routes/security_events/get_security_event.py

"""Route for reading a security event."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep
from services.security import get_security_event_for_super_admin
from services.security.schemas import SecurityEventRead

router = APIRouter()


@router.get("/{event_id}")
async def get_security_event(
    db: AsyncDbSessionDep,
    event_id: Annotated[UUID, Path()],
) -> SecurityEventRead:
    return await get_security_event_for_super_admin(db, event_id=event_id)
