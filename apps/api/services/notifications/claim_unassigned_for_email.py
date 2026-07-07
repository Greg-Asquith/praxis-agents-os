# apps/api/services/notifications/claim_unassigned_for_email.py

"""Claim pre-user notifications by email."""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification


async def claim_unassigned_for_email(db: AsyncSession, *, user_id: str, email: str) -> int:
    """Attach any pre-user notifications with matching email to the given user."""
    stmt = (
        update(Notification)
        .where(
            Notification.recipient_user_id.is_(None),
            Notification.target_email == email,
            Notification.deleted.is_(False),
        )
        .values(recipient_user_id=user_id)
    )
    res = await db.execute(stmt)
    return getattr(res, "rowcount", 0) or 0
