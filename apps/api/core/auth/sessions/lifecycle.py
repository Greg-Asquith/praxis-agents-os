# apps/api/core/auth/sessions/lifecycle.py

"""Core session lifecycle operations."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions.general import CustomValueError
from models.session import Session
from models.user import User
from utils.security import create_session_token, hash_token


class SessionLifecycleMixin:
    """Create, validate, refresh, revoke, and list sessions."""

    async def _get_valid_session(
        self,
        db: AsyncSession,
        session_token: str,
        *,
        now: datetime,
        require_twofa_verified: bool = True,
    ) -> Session | None:
        """Return a live session whose user is still allowed to authenticate."""

        try:
            token_hash = hash_token(session_token)
        except (ValueError, CustomValueError):
            return None

        conditions = [
            Session.token_hash == token_hash,
            Session.expires_at > now,
            Session.deleted.is_(False),
        ]

        if require_twofa_verified:
            conditions.append(Session.twofa_verified.is_(True))

        result = await db.execute(
            select(Session).options(selectinload(Session.user)).where(and_(*conditions))
        )
        session = result.scalar_one_or_none()
        if not session:
            return None

        user = session.user
        if not user or user.deleted or not user.is_active:
            return None

        return session

    async def create_session(
        self,
        db: AsyncSession,
        user_id: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        duration: timedelta | None = None,
        twofa_verified: bool = True,
    ) -> dict[str, Any]:
        """
        Create a new session for a user.

        Args:
            db: Database session
            user_id: User UUID
            ip_address: Client IP address
            user_agent: User agent string
            duration: Session duration (defaults to configured duration)
            twofa_verified: Whether 2FA has been verified (False for partial sessions)

        Returns:
            Dictionary with session_token, expires_at, session_id, and twofa_verified
        """
        session_token = create_session_token()
        token_hash = hash_token(session_token)

        expires_at = datetime.now(UTC) + (duration or self.default_session_duration)

        session = Session(
            user_id=user_id,
            token_hash=token_hash,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at,
            last_accessed=datetime.now(UTC),
            twofa_verified=twofa_verified,
        )

        db.add(session)
        await db.flush()
        await db.refresh(session)

        return {
            "session_token": session_token,
            "expires_at": expires_at,
            "session_id": str(session.id),
            "twofa_verified": twofa_verified,
        }

    async def validate_session(
        self,
        db: AsyncSession,
        session_token: str,
        update_last_accessed: bool = True,
        require_twofa_verified: bool = True,
    ) -> User | None:
        """
        Validate a session token and return the associated user.

        Args:
            db: Database session
            session_token: Raw session token
            update_last_accessed: Whether to update last_accessed timestamp
            require_twofa_verified: Whether to require 2FA verification (False for partial sessions)

        Returns:
            User object if session is valid, None otherwise
        """
        now = datetime.now(UTC)
        session = await self._get_valid_session(
            db,
            session_token,
            now=now,
            require_twofa_verified=require_twofa_verified,
        )

        if not session:
            return None

        # Update last accessed timestamp
        if update_last_accessed:
            session.last_accessed = now
            await db.flush()

        return session.user

    async def refresh_session(
        self, db: AsyncSession, session_token: str, duration: timedelta | None = None
    ) -> dict[str, Any] | None:
        """
        Refresh a session by extending its expiration time.

        Args:
            db: Database session
            session_token: Raw session token
            duration: New duration from now (defaults to configured duration)

        Returns:
            Dictionary with new expires_at if successful, None otherwise
        """
        now = datetime.now(UTC)
        session = await self._get_valid_session(db, session_token, now=now)

        if not session:
            return None

        # Update expiration
        new_expires_at = now + (duration or self.default_session_duration)
        session.expires_at = new_expires_at
        session.last_accessed = now

        await db.flush()

        return {"expires_at": new_expires_at, "session_id": str(session.id)}

    async def revoke_session(self, db: AsyncSession, session_token: str) -> bool:
        """
        Revoke a specific session.

        Args:
            db: Database session
            session_token: Raw session token

        Returns:
            True if session was revoked, False if not found
        """
        try:
            token_hash = hash_token(session_token)
        except (ValueError, CustomValueError):
            # Invalid/malformed token - return False
            return False

        result = await db.execute(
            select(Session).where(
                Session.token_hash == token_hash,
                Session.deleted.is_(False),
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            return False

        session.soft_delete(cascade=False)
        await db.flush()

        return True

    async def revoke_user_sessions(
        self,
        db: AsyncSession,
        user_id: str,
        exclude_session_token: str | None = None,
    ) -> int:
        """
        Revoke all sessions for a user, optionally excluding one session.

        Args:
            db: Database session
            user_id: User UUID
            exclude_session_token: Session token to keep active

        Returns:
            Number of sessions revoked
        """
        query = select(Session).where(
            Session.user_id == user_id,
            Session.deleted.is_(False),
        )

        if exclude_session_token:
            try:
                exclude_hash = hash_token(exclude_session_token)
            except (ValueError, CustomValueError):
                exclude_hash = None
            if exclude_hash is not None:
                query = query.where(Session.token_hash != exclude_hash)

        result = await db.execute(query)
        sessions = list(result.scalars().all())
        for session in sessions:
            session.soft_delete(cascade=False)
        await db.flush()

        return len(sessions)

    async def get_user_sessions(self, db: AsyncSession, user_id: str) -> list[dict[str, Any]]:
        """
        Get all active sessions for a user (for device management).

        Args:
            db: Database session
            user_id: User UUID

        Returns:
            List of session information dictionaries
        """
        now = datetime.now(UTC)

        result = await db.execute(
            select(Session)
            .where(
                and_(
                    Session.user_id == user_id,
                    Session.expires_at > now,
                    Session.deleted.is_(False),
                )
            )
            .order_by(Session.last_accessed.desc())
        )
        sessions = result.scalars().all()

        return [
            {
                "id": str(session.id),
                "ip_address": str(session.ip_address) if session.ip_address is not None else None,
                "user_agent": session.user_agent,
                "created_at": session.created_at,
                "last_accessed": session.last_accessed,
                "expires_at": session.expires_at,
            }
            for session in sessions
        ]

    _MAX_ALL_SESSIONS_PAGE_SIZE = 500

    async def get_all_user_sessions(
        self,
        db: AsyncSession,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Get active sessions for all users (for device management).

        Args:
            db: Database session
            limit: Maximum number of sessions to return (capped at 500)
            offset: Number of sessions to skip for pagination

        Returns:
            List of session information dictionaries with user details
        """
        limit = min(limit, self._MAX_ALL_SESSIONS_PAGE_SIZE)
        now = datetime.now(UTC)

        result = await db.execute(
            select(Session, User.email, User.display_name)
            .join(User, Session.user_id == User.id)
            .where(
                and_(
                    Session.user_id.is_not(None),
                    Session.expires_at > now,
                    Session.deleted.is_(False),
                )
            )
            .order_by(Session.last_accessed.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = result.all()

        return [
            {
                "id": str(session.id),
                "user_id": str(session.user_id),
                "user_email": user_email,
                "user_display_name": user_display_name,
                "ip_address": str(session.ip_address) if session.ip_address is not None else None,
                "user_agent": session.user_agent,
                "created_at": session.created_at,
                "last_accessed": session.last_accessed,
                "expires_at": session.expires_at,
            }
            for session, user_email, user_display_name in rows
        ]
