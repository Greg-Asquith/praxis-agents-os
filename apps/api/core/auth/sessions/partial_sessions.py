# apps/api/core/auth/sessions/partial_sessions.py

"""Partial session operations for two-factor authentication flows."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions.general import CustomValueError
from models.session import Session
from utils.security import hash_token


class PartialSessionMixin:
    """Create, inspect, and upgrade partial sessions."""

    async def create_partial_session(
        self,
        db: AsyncSession,
        user_id: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        redirect_url: str | None = None,
        duration: timedelta | None = None,
    ) -> dict[str, Any]:
        """
        Create a partial session that requires 2FA verification.

        Args:
            db: Database session
            user_id: User UUID
            ip_address: Client IP address
            user_agent: User agent string
            redirect_url: URL to redirect to after successful 2FA verification
            duration: Session duration (defaults to 10 minutes for partial sessions)

        Returns:
            Dictionary with session_token, expires_at, session_id, and redirect_url
        """
        # Partial sessions expire quickly (10 minutes) to encourage timely verification
        partial_duration = duration or timedelta(minutes=10)

        result = await self.create_session(
            db=db,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            duration=partial_duration,
            twofa_verified=False,
        )

        result["redirect_url"] = redirect_url
        return result

    async def upgrade_partial_session(
        self, db: AsyncSession, session_token: str
    ) -> dict[str, Any] | None:
        """
        Upgrade a partial session to a full session after 2FA verification.

        Rotates the session token to prevent session fixation: the old partial
        session row is soft-deleted and a brand-new session with
        twofa_verified=True and the normal session duration is issued.

        Args:
            db: Database session
            session_token: Raw session token of the partial session

        Returns:
            Dictionary with session_token, expires_at, session_id, and
            twofa_verified for the NEW session if successful, None otherwise.
        """
        try:
            token_hash = hash_token(session_token)
        except (ValueError, CustomValueError):
            return None

        now = datetime.now(UTC)

        result = await db.execute(
            select(Session).where(
                and_(
                    Session.token_hash == token_hash,
                    Session.expires_at > now,
                    Session.twofa_verified.is_(False),
                    Session.deleted.is_(False),
                )
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            return None

        # Capture fields needed for the new session before invalidating the old one
        user_id = str(session.user_id)
        ip_address = str(session.ip_address) if session.ip_address is not None else None
        user_agent = session.user_agent

        # Invalidate the partial session to prevent fixation attacks
        session.soft_delete(cascade=False)
        await db.flush()

        # Issue a fresh full session with a new token
        return await self.create_session(
            db=db,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            twofa_verified=True,
        )

    async def get_partial_session_info(
        self, db: AsyncSession, session_token: str
    ) -> dict[str, Any] | None:
        """
        Get information about a partial session (for 2FA verification page).

        Args:
            db: Database session
            session_token: Raw session token

        Returns:
            Dictionary with session info if valid partial session, None otherwise
        """
        try:
            token_hash = hash_token(session_token)
        except (ValueError, CustomValueError):
            return None

        now = datetime.now(UTC)

        result = await db.execute(
            select(Session)
            .options(selectinload(Session.user))
            .where(
                and_(
                    Session.token_hash == token_hash,
                    Session.expires_at > now,
                    Session.twofa_verified.is_(False),
                    Session.deleted.is_(False),
                )
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            return None

        return {
            "session_id": str(session.id),
            "user_id": str(session.user_id),
            "user_email": session.user.email,
            "expires_at": session.expires_at,
            "time_remaining_minutes": int((session.expires_at - now).total_seconds() / 60),
        }
