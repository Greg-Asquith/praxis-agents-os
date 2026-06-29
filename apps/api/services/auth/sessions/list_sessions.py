# apps/api/services/auth/list_sessions.py

"""List active sessions for the current user."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.user import User
from services.auth.schemas import SessionDevice, SessionsResponse
from services.auth.sessions.utils import current_session_id


async def list_sessions(
    db: AsyncSession,
    *,
    request: Request,
    user: User,
) -> SessionsResponse:
    active_session_id = await current_session_id(db, request)
    sessions = await session_manager.get_user_sessions(db, str(user.id))
    return SessionsResponse(
        sessions=[
            SessionDevice(
                id=session["id"],
                ip_address=session["ip_address"],
                user_agent=session["user_agent"],
                created_at=session["created_at"],
                last_accessed=session["last_accessed"],
                expires_at=session["expires_at"],
                current=session["id"] == active_session_id,
            )
            for session in sessions
        ]
    )
