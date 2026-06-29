# apps/api/services/auth/revoke_sessions.py

"""Revoke active sessions for the current user."""

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


async def revoke_sessions(
    db: AsyncSession,
    *,
    request: Request,
    response: Response,
    user: User,
    keep_current: bool,
) -> MessageResponse:
    current_session_token = session_token_from_request(request) if keep_current else None
    revoked_count = await session_manager.revoke_user_sessions(
        db,
        str(user.id),
        exclude_session_token=current_session_token,
    )
    if not keep_current:
        clear_auth_cookies(response)

    await record_auth_security_event(
        db=db,
        event_type=SecurityEventType.AUTH_SESSION_REVOKED,
        request=request,
        user_email=user.email,
        details={"revoked_sessions": revoked_count, "kept_current": keep_current},
    )
    return MessageResponse(message=f"Revoked {revoked_count} session(s)")
