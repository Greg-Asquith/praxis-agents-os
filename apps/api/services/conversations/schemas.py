# apps/api/services/conversations/schemas.py

"""Pydantic contracts for conversation routes."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.agent_run import AgentRun
from models.conversation import ConversationMessage


class ConversationTurnCreateRequest(BaseModel):
    user_prompt: str = Field(min_length=1, max_length=20000)
    client_message_id: str | None = Field(default=None, max_length=128)

    @field_validator("user_prompt")
    @classmethod
    def normalize_user_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("user_prompt must not be blank")
        return normalized

    @field_validator("client_message_id")
    @classmethod
    def normalize_client_message_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ConversationMessageRead(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    parts: dict[str, Any]
    metadata_json: dict[str, Any] | None = Field(default=None, alias="metadata")
    tool_name: str | None = None
    error_json: dict[str, Any] | None = Field(default=None, alias="error")
    sequence: int
    client_message_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @classmethod
    def from_message(cls, message: ConversationMessage) -> "ConversationMessageRead":
        return cls(
            id=message.id,
            conversation_id=message.conversation_id,
            role=message.role,
            parts=message.parts,
            metadata_json=message.metadata_json,
            tool_name=message.tool_name,
            error_json=message.error_json,
            sequence=message.sequence,
            client_message_id=message.client_message_id,
            created_at=message.created_at,
            updated_at=message.updated_at,
        )


class ConversationMessagesResponse(BaseModel):
    messages: list[ConversationMessageRead]
    total: int


class AgentRunRead(BaseModel):
    id: UUID
    conversation_id: UUID
    agent_id: UUID
    workspace_id: UUID
    user_id: UUID
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


class ConversationActiveRunResponse(BaseModel):
    active_run: AgentRunRead | None
