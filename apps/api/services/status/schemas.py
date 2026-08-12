# apps/api/services/status/schemas.py

"""Typed contracts for workspace status summaries."""

from pydantic import BaseModel, Field


class StatusSummary(BaseModel):
    """Exact operational counts for one actor in one workspace."""

    unread_conversations: int = Field(ge=0)
    conversations_needing_approval: int = Field(ge=0)
    schedules_needing_attention: int = Field(ge=0)
