# apps/api/services/audit_events/tool_events.py

"""Committed audit-event writers for runtime tool invocations."""

import logging
from typing import Any, Literal
from uuid import UUID

from core.database import get_async_db_session_factory
from models.agent import Agent
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from models.user import User
from services.audit_events.enums import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
)
from utils.json_safe import json_safe_details

logger = logging.getLogger(__name__)

ToolAuditOutcome = Literal[
    "completed",
    "approval_requested",
    "failed",
    "cancelled",
    "denied_envelope",
    "denied_approval",
    "unverified_mutation",
]


async def record_tool_invocation_audit_event(
    *,
    workspace_id: UUID | str,
    agent: Agent,
    run: AgentRun,
    tool_name: str,
    tool_provider: str,
    tool_call_id: str,
    status: AuditStatus,
    args: dict[str, Any],
    args_sha256: str,
    args_bytes: int,
    latency_ms: int | None,
    outcome: ToolAuditOutcome,
    approval_ref: str | None = None,
    error_code: str | None = None,
) -> None:
    """Record one tool invocation in an independent committed transaction."""
    try:
        session_factory = get_async_db_session_factory()
        async with session_factory() as db:
            user = await db.get(User, run.user_id)
            actor_display = _user_display(user)
            audit_context = _run_audit_context(run)
            event = AuditEvent(
                workspace_id=workspace_id,
                action=AuditAction.EXECUTE,
                resource_type=AuditResourceType.TOOL_CALL,
                resource_id=tool_call_id,
                status=status,
                summary=_tool_summary(
                    actor_display=actor_display,
                    agent=agent,
                    tool_name=tool_name,
                    status=status,
                ),
                tool_name=tool_name,
                tool_provider=tool_provider,
                actor_type=AuditActorType.USER,
                actor_id=str(run.user_id),
                actor_user_id=run.user_id,
                actor_display=actor_display,
                requested_by_user_id=run.user_id,
                details=json_safe_details(
                    {
                        "args_sha256": args_sha256,
                        "args_bytes": args_bytes,
                        "latency_ms": latency_ms,
                        "outcome": outcome,
                        "approval_ref": approval_ref,
                        "error_code": error_code,
                        "run_id": str(run.id),
                        "agent_id": str(agent.id),
                        "agent_name": agent.name,
                    }
                ),
                request_id=audit_context.get("request_id"),
                ip_address=audit_context.get("ip_address"),
                user_agent=audit_context.get("user_agent"),
            )
            db.add(event)
            await db.commit()
    except Exception:
        logger.warning("Failed to record tool invocation audit event", exc_info=True)


def _user_display(user: User | None) -> str | None:
    if user is None:
        return None
    return user.display_name or str(user.email)


def _tool_summary(
    *,
    actor_display: str | None,
    agent: Agent,
    tool_name: str,
    status: AuditStatus,
) -> str:
    actor = actor_display or "User"
    agent_name = agent.name or "agent"
    return f"{actor} ran tool {tool_name} with {agent_name}: {status}"


def _run_audit_context(run: AgentRun) -> dict[str, str | None]:
    metadata = run.metadata_json or {}
    context = metadata.get("audit_context")
    if not isinstance(context, dict):
        return {"request_id": None, "ip_address": None, "user_agent": None}
    return {
        "request_id": _string_or_none(context.get("request_id")),
        "ip_address": _string_or_none(context.get("ip_address")),
        "user_agent": _string_or_none(context.get("user_agent")),
    }


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
