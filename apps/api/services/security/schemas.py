# apps/api/services/security/schemas.py

"""Pydantic contracts for security-event read routes."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from models.security import SecurityEvent


class SecurityEventRead(BaseModel):
    id: UUID
    occurred_at: datetime
    event_type: str
    ip_address: str
    endpoint: str | None
    user_email: str | None
    user_agent: str | None
    details: dict[str, Any]
    request_id: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_event(cls, event: SecurityEvent) -> "SecurityEventRead":
        return cls.model_validate(
            {
                "id": event.id,
                "occurred_at": event.occurred_at,
                "event_type": event.event_type,
                "ip_address": str(event.ip_address),
                "endpoint": event.endpoint,
                "user_email": event.user_email,
                "user_agent": event.user_agent,
                "details": event.details or {},
                "request_id": event.request_id,
                "created_at": event.created_at,
            }
        )


class SecurityEventsListResponse(BaseModel):
    events: list[SecurityEventRead]
    total: int
    limit: int
    offset: int
