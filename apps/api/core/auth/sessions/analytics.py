# apps/api/core/auth/sessions/analytics.py

"""Session analytics and security summary operations."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.session import Session


class SessionAnalyticsMixin:
    """Report session analytics and security metrics."""

    async def get_session_analytics(
        self, db: AsyncSession, time_window_hours: int = 24
    ) -> dict[str, Any]:
        """
        Get session analytics for monitoring active users.

        Args:
            db: Database session
            time_window_hours: Time window for analytics (default 24 hours)

        Returns:
            Dictionary with session analytics
        """
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=time_window_hours)

        # Active sessions (not expired)
        active_sessions_stmt = select(func.count(Session.id)).where(
            and_(Session.expires_at > now, Session.deleted.is_(False))
        )
        active_sessions_result = await db.execute(active_sessions_stmt)
        active_sessions = active_sessions_result.scalar() or 0

        # Sessions accessed in time window
        recent_sessions_stmt = select(func.count(Session.id)).where(
            and_(Session.last_accessed >= window_start, Session.deleted.is_(False))
        )
        recent_sessions_result = await db.execute(recent_sessions_stmt)
        recent_sessions = recent_sessions_result.scalar() or 0

        # Unique active users
        active_users_stmt = select(func.count(func.distinct(Session.user_id))).where(
            and_(Session.expires_at > now, Session.deleted.is_(False))
        )
        active_users_result = await db.execute(active_users_stmt)
        active_users = active_users_result.scalar() or 0

        # Recent unique users
        recent_users_stmt = select(func.count(func.distinct(Session.user_id))).where(
            and_(Session.last_accessed >= window_start, Session.deleted.is_(False))
        )
        recent_users_result = await db.execute(recent_users_stmt)
        recent_users = recent_users_result.scalar() or 0

        # Sessions by time buckets — single query grouped by truncated hour
        hourly_stmt = (
            select(
                func.date_trunc("hour", Session.last_accessed).label("hour_bucket"),
                func.count(Session.id).label("session_count"),
            )
            .where(and_(Session.last_accessed >= window_start, Session.deleted.is_(False)))
            .group_by(func.date_trunc("hour", Session.last_accessed))
        )
        hourly_result = await db.execute(hourly_stmt)
        hourly_counts = {row.hour_bucket: row.session_count for row in hourly_result}

        hourly_sessions = []
        for i in range(time_window_hours):
            hour_start = (now - timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)
            hourly_sessions.append(
                {
                    "hour": hour_start.strftime("%Y-%m-%d %H:00"),
                    "sessions": hourly_counts.get(hour_start, 0),
                }
            )

        # Average session duration (for expired sessions in window)
        expired_in_window_stmt = select(
            func.avg(func.extract("epoch", Session.last_accessed - Session.created_at))
        ).where(
            and_(
                Session.expires_at <= now,
                Session.created_at >= window_start,
                Session.deleted.is_(False),
            )
        )
        avg_duration_result = await db.execute(expired_in_window_stmt)
        avg_duration_seconds = avg_duration_result.scalar()
        avg_duration_minutes = int(avg_duration_seconds / 60) if avg_duration_seconds else 0

        return {
            "time_window_hours": time_window_hours,
            "timestamp": now.isoformat(),
            "active_sessions": active_sessions,
            "recent_sessions": recent_sessions,
            "active_users": active_users,
            "recent_users": recent_users,
            "avg_session_duration_minutes": avg_duration_minutes,
            "hourly_breakdown": hourly_sessions,
        }

    async def get_user_session_stats(self, db: AsyncSession, user_id: str) -> dict[str, Any]:
        """
        Get session statistics for a specific user.

        Args:
            db: Database session
            user_id: User UUID

        Returns:
            Dictionary with user session statistics
        """
        now = datetime.now(UTC)

        # Current active sessions
        active_sessions_stmt = (
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

        active_sessions_result = await db.execute(active_sessions_stmt)
        active_sessions = active_sessions_result.scalars().all()

        # Total sessions (last 30 days)
        thirty_days_ago = now - timedelta(days=30)
        total_sessions_stmt = select(func.count(Session.id)).where(
            and_(
                Session.user_id == user_id,
                Session.created_at >= thirty_days_ago,
                Session.deleted.is_(False),
            )
        )
        total_sessions_result = await db.execute(total_sessions_stmt)
        total_sessions = total_sessions_result.scalar() or 0

        # Most recent session
        recent_session_stmt = (
            select(Session)
            .where(and_(Session.user_id == user_id, Session.deleted.is_(False)))
            .order_by(Session.last_accessed.desc())
            .limit(1)
        )

        recent_session_result = await db.execute(recent_session_stmt)
        recent_session = recent_session_result.scalar_one_or_none()

        # Session details
        active_session_details = [
            {
                "session_id": str(session.id),
                "ip_address": str(session.ip_address) if session.ip_address else None,
                "user_agent": session.user_agent,
                "created_at": session.created_at.isoformat(),
                "last_accessed": session.last_accessed.isoformat(),
                "expires_at": session.expires_at.isoformat(),
                "is_current": False,  # Will be set by caller if this matches current session
            }
            for session in active_sessions
        ]

        return {
            "user_id": user_id,
            "active_sessions_count": len(active_sessions),
            "total_sessions_30d": total_sessions,
            "last_activity": recent_session.last_accessed.isoformat() if recent_session else None,
            "active_sessions": active_session_details,
        }

    async def get_session_security_summary(
        self, db: AsyncSession, time_window_hours: int = 24
    ) -> dict[str, Any]:
        """
        Get session security summary for monitoring.

        Args:
            db: Database session
            time_window_hours: Time window for analysis

        Returns:
            Dictionary with security metrics
        """
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=time_window_hours)

        # Sessions from different IPs for same user
        multi_ip_users_stmt = (
            select(
                Session.user_id,
                func.count(func.distinct(Session.ip_address)).label("ip_count"),
            )
            .where(
                and_(
                    Session.expires_at > now,
                    Session.ip_address.isnot(None),
                    Session.deleted.is_(False),
                )
            )
            .group_by(Session.user_id)
            .having(func.count(func.distinct(Session.ip_address)) > 1)
        )

        multi_ip_result = await db.execute(multi_ip_users_stmt)
        multi_ip_users = multi_ip_result.fetchall()

        # High session count users (potential account sharing)
        high_session_users_stmt = (
            select(Session.user_id, func.count(Session.id).label("session_count"))
            .where(and_(Session.expires_at > now, Session.deleted.is_(False)))
            .group_by(Session.user_id)
            .having(func.count(Session.id) > 5)
        )

        high_session_result = await db.execute(high_session_users_stmt)
        high_session_users = high_session_result.fetchall()

        # Recent sessions from new IPs
        # This would require tracking IP history, simplified for now
        unique_ips_stmt = select(func.count(func.distinct(Session.ip_address))).where(
            and_(
                Session.created_at >= window_start,
                Session.ip_address.isnot(None),
                Session.deleted.is_(False),
            )
        )
        unique_ips_result = await db.execute(unique_ips_stmt)
        unique_ips = unique_ips_result.scalar() or 0

        return {
            "time_window_hours": time_window_hours,
            "timestamp": now.isoformat(),
            "users_with_multiple_ips": len(multi_ip_users),
            "users_with_high_session_count": len(high_session_users),
            "unique_ips_in_window": unique_ips,
            "multi_ip_details": [
                {"user_id": str(row.user_id), "ip_count": row.ip_count}
                for row in multi_ip_users[:10]  # Top 10
            ],
            "high_session_details": [
                {"user_id": str(row.user_id), "session_count": row.session_count}
                for row in high_session_users[:10]  # Top 10
            ],
        }
