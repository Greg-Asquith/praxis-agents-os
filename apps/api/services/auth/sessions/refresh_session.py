# apps/api/services/auth/refresh_session.py

"""Refresh the current session."""

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.exceptions.auth import AuthenticationError
from models.user import User
from services.auth.schemas import AuthResponse, AuthSession, AuthUser
from services.auth.utils import (
    record_auth_security_event,
    session_token_from_request,
    set_auth_cookies,
)
from services.security import SecurityEventType


async def refresh_session(
    db: AsyncSession,
    *,
    request: Request,
    response: Response,
    user: User,
) -> AuthResponse:
    session_token = session_token_from_request(request)
    if not session_token:
        raise AuthenticationError("No active session")

    refreshed = await session_manager.refresh_session(db, session_token)
    if not refreshed:
        raise AuthenticationError("No active session")

    set_auth_cookies(response, session_token=session_token, expires_at=refreshed["expires_at"])
    await record_auth_security_event(
        db=db,
        event_type=SecurityEventType.AUTH_SESSION_REFRESHED,
        request=request,
        user_email=user.email,
        details={"session_id": refreshed["session_id"]},
    )
    return AuthResponse(
        user=AuthUser.from_user(user),
        session=AuthSession(expires_at=refreshed["expires_at"], twofa_verified=True),
        requires_twofa=False,
    )
