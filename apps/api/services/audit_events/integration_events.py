# apps/api/services/audit_events/integration_events.py

"""Committed per-resource audit records for integration operations."""

import logging
from uuid import UUID

from core.database import get_async_db_session_factory
from models.agent import Agent
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from services.audit_events.enums import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
)
from utils.json_safe import json_safe_details

logger = logging.getLogger(__name__)


async def record_integration_operation_audit_event(
    *,
    workspace_id: UUID,
    agent: Agent,
    run: AgentRun,
    tool_name: str,
    provider_key: str,
    connection_id: UUID,
    integration_resource_id: UUID,
    external_id: str,
    operation: str,
    status: AuditStatus,
    external_ref: str | None,
    error_code: str | None,
) -> None:
    """Record one provider operation in an independent transaction."""
    try:
        session_factory = get_async_db_session_factory()
        async with session_factory() as db:
            event = AuditEvent(
                workspace_id=workspace_id,
                action=AuditAction.EXECUTE,
                resource_type=AuditResourceType.INTEGRATION_RESOURCE,
                resource_id=str(integration_resource_id),
                status=status,
                summary=(
                    f"Agent {agent.name or agent.id} ran {operation} on "
                    f"{provider_key} resource {external_id}: {status}"
                ),
                tool_name=tool_name,
                tool_provider=provider_key,
                actor_type=AuditActorType.AGENT,
                actor_id=str(agent.id),
                actor_display=agent.name,
                requested_by_user_id=run.user_id,
                details=json_safe_details(
                    {
                        "run_id": str(run.id),
                        "connection_id": str(connection_id),
                        "integration_resource_id": str(integration_resource_id),
                        "external_id": external_id,
                        "provider_operation": operation,
                        "external_ref": external_ref,
                        "error_code": error_code,
                    }
                ),
            )
            db.add(event)
            await db.commit()
    except Exception:
        logger.warning("Failed to record integration operation audit event", exc_info=True)
