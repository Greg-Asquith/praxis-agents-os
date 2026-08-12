# apps/api/services/audit_events/integration_events.py

"""Committed per-resource audit records for integration operations."""

import logging
from uuid import UUID

from core.database import get_async_db_session_factory, set_session_tenant_context
from models.agent import Agent
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from services.audit_events.enums import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
)
from services.audit_events.integration_operation_detail import IntegrationOperationDetail
from utils.json_safe import json_safe_details

logger = logging.getLogger(__name__)


async def record_integration_operation_audit_event(
    *,
    workspace_id: UUID,
    agent: Agent,
    run: AgentRun,
    tool_call_id: str | None,
    tool_name: str,
    provider_key: str,
    connection_id: UUID,
    integration_resource_id: UUID,
    external_id: str,
    operation: str,
    status: AuditStatus,
    external_ref: str | None,
    error_code: str | None,
    operation_detail: IntegrationOperationDetail | None = None,
    related_event_id: UUID | None = None,
    raise_on_error: bool = False,
) -> UUID | None:
    """Record one provider operation in an independent transaction.

    Strict callers receive persistence errors so external writes cannot silently
    outlive the durable evidence promised to operators.
    """
    try:
        session_factory = get_async_db_session_factory()
        async with session_factory() as db:
            await set_session_tenant_context(
                db,
                workspace_id=workspace_id,
                user_id=run.user_id,
            )
            details = {
                "run_id": str(run.id),
                "tool_call_id": tool_call_id,
                "connection_id": str(connection_id),
                "integration_resource_id": str(integration_resource_id),
                "external_id": external_id,
                "provider_operation": operation,
                "external_ref": external_ref,
                "error_code": error_code,
                "related_event_id": str(related_event_id) if related_event_id else None,
            }
            if operation_detail is not None:
                details["operation_detail"] = operation_detail.model_dump(mode="json")
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
                details=json_safe_details(details),
            )
            db.add(event)
            await db.flush()
            event_id = event.id
            await db.commit()
            return event_id
    except Exception:
        logger.warning("Failed to record integration operation audit event", exc_info=True)
        if raise_on_error:
            raise
        return None
