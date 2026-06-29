# apps/api/services/audit_events/operations.py

"""Audit-event writers for routine workspace operations."""

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.rate_limiting import get_client_ip
from models.audit_event import AuditEvent
from services.audit_events.enums import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
)
from utils.json_safe import json_safe_details

logger = logging.getLogger(__name__)


async def _record_operation_audit_event(
    db: AsyncSession,
    *,
    workspace_id: UUID | str | None,
    action: AuditAction,
    resource_type: AuditResourceType,
    actor_type: AuditActorType,
    actor_id: UUID | str | None = None,
    actor_display: str | None = None,
    status: AuditStatus = AuditStatus.SUCCESS,
    resource_id: UUID | str | None = None,
    requested_by_user_id: UUID | str | None = None,
    details: Mapping[str, Any] | None = None,
    request: Request | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    occurred_at: datetime | None = None,
) -> AuditEvent:
    """Persist one audit event using the caller-owned database session.

    Private: callers use :func:`safe_record_operation_audit_event` so an audit
    write failure can never roll back the work being recorded.
    """

    request_context = _request_context(request)
    event = AuditEvent(
        workspace_id=_uuid_or_none(workspace_id),
        occurred_at=occurred_at or datetime.now(UTC),
        action=action,
        resource_type=resource_type,
        resource_id=_string_or_none(resource_id),
        status=status,
        summary=_summary(
            actor_display=actor_display,
            actor_type=actor_type,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status=status,
        ),
        actor_type=actor_type,
        actor_id=_string_or_none(actor_id),
        actor_user_id=_uuid_or_none(actor_id) if actor_type == AuditActorType.USER else None,
        actor_display=actor_display,
        requested_by_user_id=_uuid_or_none(requested_by_user_id),
        details=json_safe_details(details or {}),
        request_id=request_id or request_context.get("request_id"),
        ip_address=ip_address or request_context.get("ip_address"),
        user_agent=user_agent or request_context.get("user_agent"),
    )
    db.add(event)
    await db.flush()
    return event


async def safe_record_operation_audit_event(db: AsyncSession, **kwargs: Any) -> None:
    """Record an audit event in a savepoint so a failure never rolls back the
    caller's already-successful work; the audit loss is logged instead.

    This is the only supported way to write an audit event: auditing must never
    stop the thing it audits from happening.
    """
    try:
        async with db.begin_nested():
            await _record_operation_audit_event(db, **kwargs)
    except Exception:
        logger.error("Failed to record audit event; primary operation preserved", exc_info=True)


def _request_context(request: Request | None) -> dict[str, str | None]:
    if request is None:
        return {"request_id": None, "ip_address": None, "user_agent": None}

    audit_context = getattr(request.state, "audit_context", None)
    if isinstance(audit_context, dict):
        return {
            "request_id": audit_context.get("request_id"),
            "ip_address": audit_context.get("ip_address"),
            "user_agent": audit_context.get("user_agent"),
        }

    return {
        "request_id": request.scope.get("request_id") or request.headers.get("x-request-id"),
        "ip_address": get_client_ip(request),
        "user_agent": request.headers.get("user-agent"),
    }


def _summary(
    *,
    actor_display: str | None,
    actor_type: AuditActorType,
    action: AuditAction,
    resource_type: AuditResourceType,
    resource_id: Any,
    status: AuditStatus,
) -> str:
    actor = actor_display or actor_type
    target = f"{resource_type} {resource_id}" if resource_id else resource_type
    return f"{actor} {action} {target}: {status}"


def _uuid_or_none(value: Any) -> UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
