# apps/api/services/agent_runs/schemas.py

"""Pydantic contracts for agent-run routes."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.agent_run import AgentRun
from utils.validation import normalize_optional_text

ResumeDecision = Literal["approved", "denied"]


class AgentRunResumeDecision(BaseModel):
    tool_call_id: str = Field(min_length=1, max_length=256)
    decision: ResumeDecision
    message: str | None = Field(default=None, max_length=1000)
    override_args: dict[str, Any] | None = None

    @field_validator("tool_call_id")
    @classmethod
    def normalize_tool_call_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tool_call_id must not be blank")
        return normalized

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_override_args(self) -> "AgentRunResumeDecision":
        if self.decision == "denied" and self.override_args is not None:
            raise ValueError("override_args can only be provided for approved decisions")
        return self


class AgentRunResumeRequest(BaseModel):
    decisions: list[AgentRunResumeDecision] = Field(min_length=1)


class PendingDelegatedApprovalRead(BaseModel):
    parent_tool_call_id: str
    child_agent_id: UUID
    child_agent_name: str
    child_conversation_id: UUID
    child_run_id: UUID
    pending_approval_count: int = Field(ge=0)


class PendingToolApprovalRead(BaseModel):
    tool_call_id: str
    name: str
    args: Any
    delegation: PendingDelegatedApprovalRead | None = None


class AgentRunApprovalStateResponse(BaseModel):
    run_id: UUID
    conversation_id: UUID
    approvals: list[PendingToolApprovalRead]
    delegations: list[PendingDelegatedApprovalRead] = Field(default_factory=list)


class AgentRunRead(BaseModel):
    id: UUID
    conversation_id: UUID
    agent_id: UUID
    workspace_id: UUID
    user_id: UUID
    parent_run_id: UUID | None = None
    delegation_depth: int
    trigger: str
    status: str
    model_name: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_run(cls, run: AgentRun) -> "AgentRunRead":
        return cls.model_validate(run)


class AgentRunCancelResponse(BaseModel):
    run: AgentRunRead
    local_cancel_delivered: bool
