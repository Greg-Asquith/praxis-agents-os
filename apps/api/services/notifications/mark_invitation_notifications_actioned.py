# apps/api/services/notifications/mark_invitation_notifications_actioned.py

"""Mark invitation notifications actioned."""

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification
from models.user import User


async def mark_invitation_notifications_actioned(
    db: AsyncSession,
    *,
    user: User,
    invitation_id: str,
) -> int:
    """Mark workspace_invite notifications as actioned/read after email-link acceptance.

    Matches notifications by invitation_id in payload for either the current
    user or the same target_email (pre-claimed). Also claims recipient_user_id
    to the current user.
    """
    stmt = select(Notification).where(
        Notification.notification_type == "workspace_invite",
        Notification.deleted.is_(False),
        Notification.payload["invitation_id"].astext == str(invitation_id),
        or_(
            Notification.recipient_user_id == user.id,
            Notification.target_email == user.email,
        ),
    )
    res = await db.execute(stmt)
    notes = list(res.scalars().all())
    now = datetime.now(UTC)
    count = 0
    for note in notes:
        note.recipient_user_id = note.recipient_user_id or user.id
        note.read_at = note.read_at or now
        note.actioned_at = note.actioned_at or now
        note.action_taken = note.action_taken or "accept_invite"
        note.actions = []
        count += 1
    return count
