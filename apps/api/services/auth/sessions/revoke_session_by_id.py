# apps/api/services/auth/revoke_session_by_id.py

"""Revoke a single active session by ID."""

from uuid import UUID

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.auth.schemas import MessageResponse
from services.auth.sessions.utils import current_session_id, get_user_session_by_id
from services.auth.utils import clear_auth_cookies, record_auth_security_event
from services.security import SecurityEventType


async def revoke_session_by_id(
    db: AsyncSession,
    *,
    request: Request,
    response: Response,
    user: User,
    session_id: UUID,
) -> MessageResponse:
    session = await get_user_session_by_id(db, user=user, session_id=session_id)
    active_session_id = await current_session_id(db, request)
    session.soft_delete(cascade=False)
    await db.flush()

    revoked_current = str(session.id) == active_session_id
    if revoked_current:
        clear_auth_cookies(response)

    await record_auth_security_event(
        db=db,
        event_type=SecurityEventType.AUTH_SESSION_REVOKED,
        request=request,
        user_email=user.email,
        details={"session_id": str(session.id), "current": revoked_current},
    )
    return MessageResponse(message="Session revoked")
