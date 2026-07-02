# apps/api/services/agents/runtime/delegation/schemas.py

"""Pydantic schemas used by delegation runtime tools."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DelegateAgentSummary(BaseModel):
    """A model-facing summary of one visible delegate agent."""

    id: UUID
    slug: str
    name: str
    description: str | None = None
    model: str | None = None
    tool_count: int
    skill_count: int


class DelegateRunResult(BaseModel):
    """Structured result returned from a delegated child run."""

    status: Literal["completed", "awaiting_approval", "failed"]
    agent_id: UUID
    agent_name: str
    run_id: UUID | None = None
    conversation_id: UUID | None = None
    output: str | None = None
    error: str | None = None
    pending_approvals: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False
