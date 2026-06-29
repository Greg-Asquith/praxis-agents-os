# apps/api/services/auth/logout.py

"""Logout the current user."""

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.user import User
from services.auth.schemas import MessageResponse
from services.auth.utils import (
    clear_auth_cookies,
    record_auth_security_event,
    session_token_from_request,
)
from services.security import SecurityEventType


async def logout(
    db: AsyncSession,
    *,
    request: Request,
    response: Response,
    user: User | None,
) -> MessageResponse:
    session_token = session_token_from_request(request)
    revoked = False
    if session_token:
        revoked = await session_manager.revoke_session(db, session_token)

    clear_auth_cookies(response)

    if user is not None or revoked:
        await record_auth_security_event(
            db=db,
            event_type=SecurityEventType.AUTH_LOGOUT_SUCCEEDED,
            request=request,
            user_email=user.email if user else None,
            details={"revoked": revoked},
        )
    return MessageResponse(message="Logged out")
