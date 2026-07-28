# apps/api/services/integrations/connections/transition_connection_status.py

"""Guard and audit the integration connection status machine."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationConnectionError
from models.integrations import ExternalCredential, IntegrationConnection
from services.audit_events import AuditAction, AuditResourceType, AuditStatus
from services.integrations.domain import CONNECTION_STATUS_TRANSITIONS, CONNECTION_STATUSES
from services.integrations.utils import record_integration_audit


async def transition_connection_status(
    db: AsyncSession,
    connection: IntegrationConnection,
    status: str,
    *,
    reason: str | None = None,
    audit_action: AuditAction = AuditAction.UPDATE,
    audit_status: AuditStatus = AuditStatus.SUCCESS,
    audit_details: dict[str, Any] | None = None,
    audit_workspace_id: UUID | None = None,
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
    if status in {"needs_reauth", "needs_credential"}:
        auth_mode = await db.scalar(
            select(ExternalCredential.auth_mode).where(
                ExternalCredential.id == connection.credential_id,
                ExternalCredential.deleted.is_(False),
            )
        )
        expected_oauth = status == "needs_reauth"
        if auth_mode is None or (auth_mode == "oauth") != expected_oauth:
            raise IntegrationConnectionError(
                "Credential recovery status does not match the connection authentication mode",
                provider_key=connection.provider_key,
                connection_id=str(connection.id),
                operation="transition_status",
            )
    connection.status = status
    connection.status_reason = reason
    connection.status_changed_at = datetime.now(UTC)
    await db.flush()
    details = {"from": previous, "to": status, "reason": reason}
    details.update(audit_details or {})
    await record_integration_audit(
        db,
        workspace_id=audit_workspace_id or connection.owner_workspace_id,
        action=audit_action,
        resource_type=AuditResourceType.INTEGRATION_CONNECTION,
        resource_id=connection.id,
        details=details,
        status=audit_status,
    )
    if status in {"needs_reauth", "needs_credential"}:
        from services.integrations.connections.notify_connection_event import (
            notify_connection_event,
        )

        await notify_connection_event(
            db,
            connection_id=connection.id,
            event=status,
        )
    return connection
