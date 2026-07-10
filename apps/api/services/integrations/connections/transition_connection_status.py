# apps/api/services/integrations/connections/transition_connection_status.py

"""Guard and audit the integration connection status machine."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationConnectionError
from models.integrations import IntegrationConnection
from services.audit_events import AuditAction, AuditResourceType
from services.integrations.domain import CONNECTION_STATUS_TRANSITIONS, CONNECTION_STATUSES
from services.integrations.utils import record_integration_audit


async def transition_connection_status(
    db: AsyncSession,
    connection: IntegrationConnection,
    status: str,
    *,
    reason: str | None = None,
) -> IntegrationConnection:
    previous = connection.status
    if status == previous:
        return connection
    if status not in CONNECTION_STATUSES or status not in CONNECTION_STATUS_TRANSITIONS[previous]:
        raise IntegrationConnectionError(
            "Invalid integration connection status transition",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="transition_status",
        )
    connection.status = status
    connection.status_reason = reason
    connection.status_changed_at = datetime.now(UTC)
    await db.flush()
    await record_integration_audit(
        db,
        workspace_id=connection.owner_workspace_id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.INTEGRATION_CONNECTION,
        resource_id=connection.id,
        details={"from": previous, "to": status, "reason": reason},
    )
    return connection
