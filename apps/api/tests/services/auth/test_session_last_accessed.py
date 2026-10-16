# apps/api/tests/services/auth/test_session_last_accessed.py

"""Session validation writes last_accessed only when it is stale."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions.session_manager import session_manager
from models.session import Session
from tests.factories import build_session, build_user
from utils.security import create_session_token, hash_token

pytestmark = pytest.mark.asyncio


async def _stored_last_accessed(db: AsyncSession, session: Session) -> datetime:
    return await db.scalar(select(Session.last_accessed).where(Session.id == session.id))


async def test_validate_session_refreshes_only_stale_last_accessed(
    db_session: AsyncSession,
) -> None:
    user = build_user(email="last-accessed@example.com")
    token = create_session_token()
    session = build_session(user_id=user.id, token_hash=hash_token(token))
    stale = datetime.now(UTC) - timedelta(minutes=10)
    session.last_accessed = stale
    db_session.add_all([user, session])
    await db_session.flush()

    assert await session_manager.validate_session(db_session, token) is not None
    refreshed = await _stored_last_accessed(db_session, session)
    assert refreshed > stale

    recent = datetime.now(UTC) - timedelta(minutes=1)
    session.last_accessed = recent
    await db_session.flush()

    assert await session_manager.validate_session(db_session, token) is not None
    assert await _stored_last_accessed(db_session, session) == recent
