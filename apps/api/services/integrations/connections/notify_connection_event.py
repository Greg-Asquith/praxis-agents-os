# apps/api/services/integrations/connections/notify_connection_event.py

"""Emit user-facing integration connection lifecycle notifications."""

from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationNotFoundError
from models.integrations import IntegrationConnection
from services.notifications import create_notification

ConnectionEvent = Literal["needs_reauth", "needs_credential", "discovery_failed"]


async def notify_connection_event(
    db: AsyncSession,
    *,
    connection_id: UUID,
    event: ConnectionEvent,
) -> None:
    connection = await db.get(IntegrationConnection, connection_id)
    if connection is None:
        raise IntegrationNotFoundError(
            "Integration connection not found",
            connection_id=str(connection_id),
            operation="notify_connection_event",
        )
    titles = {
        "needs_reauth": "Reconnect integration",
        "needs_credential": "Replace integration credential",
        "discovery_failed": "Integration refresh failed",
    }
    await create_notification(
        db,
        notification_type=f"integration_{event}",
        title=titles[event],
        payload={
            "connection_id": str(connection.id),
            "provider_key": connection.provider_key,
            "label": connection.label,
        },
        recipient_user_id=str(connection.connected_by_user_id),
        workspace_id=(
            str(connection.owner_workspace_id) if connection.owner_workspace_id else None
        ),
        source="integrations",
    )
