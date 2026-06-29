# apps/api/core/auth/sessions/cleanup.py

"""Session cleanup and cleanup summary operations."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.session import Session


class SessionCleanupMixin:
    """Clean up expired, old, and inactive sessions."""

    async def cleanup_expired_sessions(self, db: AsyncSession) -> int:
        """
        Remove all expired sessions from the database.

        The changes are flushed but NOT committed. The caller is responsible
        for committing the transaction.

        Args:
            db: Database session

        Returns:
            Number of sessions cleaned up
        """
        now = datetime.now(UTC)

        result = await db.execute(delete(Session).where(Session.expires_at <= now))
        await db.flush()
        return result.rowcount

    async def cleanup_old_sessions(
        self, db: AsyncSession, days_old: int = 30, keep_active: bool = True
    ) -> int:
        """
        Remove old sessions beyond a certain age, optionally keeping active ones.

        The changes are flushed but NOT committed. The caller is responsible
        for committing the transaction.

        Args:
            db: Database session
            days_old: Remove sessions older than this many days
            keep_active: If True, only remove expired sessions regardless of age

        Returns:
            Number of sessions cleaned up
        """
        cutoff_date = datetime.now(UTC) - timedelta(days=days_old)
        now = datetime.now(UTC)

        if keep_active:
            # Only remove old sessions that are also expired
            result = await db.execute(
                delete(Session).where(
                    and_(Session.created_at <= cutoff_date, Session.expires_at <= now)
                )
            )
        else:
            # Remove all old sessions regardless of expiry
            result = await db.execute(delete(Session).where(Session.created_at <= cutoff_date))

        await db.flush()
        return result.rowcount

    async def cleanup_inactive_sessions(
        self, db: AsyncSession, days_inactive: int = 7, keep_active: bool = True
    ) -> int:
        """
        Remove sessions that haven't been accessed for a specified period.

        The changes are flushed but NOT committed. The caller is responsible
        for committing the transaction.

        Args:
            db: Database session
            days_inactive: Remove sessions not accessed for this many days
            keep_active: If True (default), only remove inactive sessions that
                are also expired, so a still-valid session is never force-logged
                out for inactivity.

        Returns:
            Number of sessions cleaned up
        """
        cutoff_date = datetime.now(UTC) - timedelta(days=days_inactive)
        now = datetime.now(UTC)

        if keep_active:
            result = await db.execute(
                delete(Session).where(
                    and_(Session.last_accessed <= cutoff_date, Session.expires_at <= now)
                )
            )
        else:
            result = await db.execute(delete(Session).where(Session.last_accessed <= cutoff_date))
        await db.flush()
        return result.rowcount

    async def get_cleanup_summary(self, db: AsyncSession) -> dict[str, Any]:
        """
        Get summary of sessions that could be cleaned up.

        Args:
            db: Database session

        Returns:
            Dictionary with cleanup statistics
        """
        now = datetime.now(UTC)
        thirty_days_ago = now - timedelta(days=30)
        seven_days_ago = now - timedelta(days=7)

        # Expired sessions
        expired_stmt = select(func.count(Session.id)).where(Session.expires_at <= now)
        expired_result = await db.execute(expired_stmt)
        expired_count = expired_result.scalar() or 0

        # Old sessions (30+ days)
        old_stmt = select(func.count(Session.id)).where(Session.created_at <= thirty_days_ago)
        old_result = await db.execute(old_stmt)
        old_count = old_result.scalar() or 0

        # Inactive sessions (7+ days)
        inactive_stmt = select(func.count(Session.id)).where(
            Session.last_accessed <= seven_days_ago
        )
        inactive_result = await db.execute(inactive_stmt)
        inactive_count = inactive_result.scalar() or 0

        # Total sessions
        total_stmt = select(func.count(Session.id))
        total_result = await db.execute(total_stmt)
        total_count = total_result.scalar() or 0

        # Active sessions
        active_stmt = select(func.count(Session.id)).where(
            and_(Session.expires_at > now, Session.deleted.is_(False))
        )
        active_result = await db.execute(active_stmt)
        active_count = active_result.scalar() or 0

        return {
            "timestamp": now.isoformat(),
            "total_sessions": total_count,
            "active_sessions": active_count,
            "expired_sessions": expired_count,
            "old_sessions_30d": old_count,
            "inactive_sessions_7d": inactive_count,
            "cleanup_recommendations": {
                "expired": expired_count > 0,
                "old": old_count > 1000,  # If more than 1000 old sessions
                "inactive": inactive_count > 500,  # If more than 500 inactive sessions
            },
        }
