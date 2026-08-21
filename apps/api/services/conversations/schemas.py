# apps/api/services/conversations/schemas.py

"""Pydantic contracts for conversation routes."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.conversation import ConversationMessage
from services.agent_runs.schemas import AgentRunRead
from services.conversation_read_contract import ConversationRead
from services.integrations.context.schemas import ActiveContextTargets
from utils.pagination import OffsetPage
from utils.validation import normalize_optional_text


class ConversationCreateRequest(BaseModel):
    agent_id: UUID
    user_prompt: str = Field(min_length=1, max_length=20000)
    client_message_id: str | None = Field(default=None, max_length=128)
    attachments: list[UUID] = Field(default_factory=list)
    active_context: ActiveContextTargets | None = None

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
        return normalize_optional_text(value)

    @field_validator("attachments")
    @classmethod
    def dedupe_attachments(cls, value: list[UUID]) -> list[UUID]:
        return _dedupe_attachment_ids(value)


class ConversationTurnCreateRequest(BaseModel):
    user_prompt: str = Field(min_length=1, max_length=20000)
    client_message_id: str | None = Field(default=None, max_length=128)
    attachments: list[UUID] = Field(default_factory=list)

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
        return normalize_optional_text(value)

    @field_validator("attachments")
    @classmethod
    def dedupe_attachments(cls, value: list[UUID]) -> list[UUID]:
        return _dedupe_attachment_ids(value)


def _dedupe_attachment_ids(value: list[UUID]) -> list[UUID]:
    seen: set[UUID] = set()
    deduped: list[UUID] = []
    for attachment_id in value:
        if attachment_id in seen:
            continue
        seen.add(attachment_id)
        deduped.append(attachment_id)
    return deduped


class ConversationMessageRead(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    parts: dict[str, Any]
    metadata_json: dict[str, Any] | None = Field(default=None, serialization_alias="metadata")
    tool_name: str | None = None
    error_json: dict[str, Any] | None = Field(default=None, serialization_alias="error")
    sequence: int
    client_message_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @classmethod
    def from_message(cls, message: ConversationMessage) -> "ConversationMessageRead":
        return cls.model_validate(message)


class ConversationMessagesResponse(BaseModel):
    messages: list[ConversationMessageRead]
    total: int
    has_more: bool = False


class ConversationActiveRunResponse(BaseModel):
    active_run: AgentRunRead | None
    latest_run: AgentRunRead | None
    approval_expires_at: datetime | None


class ConversationsListResponse(OffsetPage):
    conversations: list[ConversationRead]
