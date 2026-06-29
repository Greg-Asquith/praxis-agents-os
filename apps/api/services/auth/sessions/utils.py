# apps/api/services/auth/sessions/utils.py

"""Session specific helpers for auth operations."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.session import Session
from models.user import User
from services.auth.utils import session_token_from_request
from utils.security import hash_token


async def current_session_id(db: AsyncSession, request: Request) -> str | None:
    session_token = session_token_from_request(request)
    if not session_token:
        return None
    try:
        token_hash = hash_token(session_token)
    except Exception:
        return None
    result = await db.execute(
        select(Session.id).where(
            Session.token_hash == token_hash,
            Session.deleted.is_(False),
        )
    )
    session_id = result.scalar_one_or_none()
    return str(session_id) if session_id else None


async def get_user_session_by_id(
    db: AsyncSession,
    *,
    user: User,
    session_id: UUID,
) -> Session:
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == user.id,
            Session.deleted.is_(False),
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise NotFoundError("Session not found", resource_type="session", resource_id=str(session_id))
    return session
