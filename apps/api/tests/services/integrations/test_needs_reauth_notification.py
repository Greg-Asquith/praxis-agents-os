"""Edge-triggered reauthentication notifications."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification
from services.integrations.connections.transition_connection_status import (
    transition_connection_status,
)


async def test_needs_reauth_notification_fires_once_per_transition(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    await transition_connection_status(db_session, connection, "needs_reauth")
    await transition_connection_status(db_session, connection, "needs_reauth")
    count = await db_session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.notification_type == "integration_needs_reauth")
    )
    assert count == 1

    await transition_connection_status(db_session, connection, "discovery_pending")
    await transition_connection_status(db_session, connection, "needs_reauth")
    count = await db_session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.notification_type == "integration_needs_reauth")
    )
    assert count == 2
