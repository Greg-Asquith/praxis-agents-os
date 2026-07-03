# apps/api/services/audit_events/schemas.py

"""Pydantic contracts for audit-event read routes."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from models.audit_event import AuditEvent


class AuditEventRead(BaseModel):
    id: UUID
    workspace_id: UUID | None
    occurred_at: datetime
    action: str
    resource_type: str
    resource_id: str | None
    status: str
    summary: str
    actor_type: str
    actor_id: str | None
    actor_user_id: UUID | None
    actor_display: str | None
    requested_by_user_id: UUID | None
    details: dict[str, Any]
    request_id: str | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_event(cls, event: AuditEvent) -> "AuditEventRead":
        return cls.model_validate(
            {
                "id": event.id,
                "workspace_id": event.workspace_id,
                "occurred_at": event.occurred_at,
                "action": event.action,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "status": event.status,
                "summary": event.summary,
                "actor_type": event.actor_type,
                "actor_id": event.actor_id,
                "actor_user_id": event.actor_user_id,
                "actor_display": event.actor_display,
                "requested_by_user_id": event.requested_by_user_id,
                "details": event.details or {},
                "request_id": event.request_id,
                "ip_address": event.ip_address,
                "user_agent": event.user_agent,
                "created_at": event.created_at,
            }
        )


class AuditEventsListResponse(BaseModel):
    events: list[AuditEventRead]
    total: int
    limit: int
    offset: int
