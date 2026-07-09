# apps/api/services/conversations/schemas.py

"""Pydantic contracts for conversation routes."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.conversation import Conversation, ConversationMessage
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agent_runs.schemas import AgentRunRead
from utils.pagination import OffsetPage
from utils.validation import normalize_optional_text

ConversationSource = Literal["direct", "scheduled", "delegated"]


class ConversationCreateRequest(BaseModel):
    agent_id: UUID
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


class ConversationRead(BaseModel):
    id: UUID
    user_id: UUID
    workspace_id: UUID
    created_by: UUID
    title: str | None = None
    description: str | None = None
    status: str
    metadata_json: dict[str, Any] | None = Field(default=None, serialization_alias="metadata")
    unread: bool
    source: ConversationSource
    last_message_at: datetime | None = None
    active_agent_id: UUID | None = None
    agent_slug: str | None = None
    agent_name: str | None = None
    active_run_id: UUID | None = None
    active_run_status: str | None = None
    needs_approval: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @classmethod
    def from_conversation(cls, conversation: Conversation) -> "ConversationRead":
        return cls.model_validate(conversation)

    @classmethod
    def from_projection(
        cls,
        conversation: Conversation,
        *,
        agent_name: str | None,
        active_run_id: UUID | None,
        active_run_status: str | None,
    ) -> "ConversationRead":
        read_model = cls.from_conversation(conversation)
        return read_model.model_copy(
            update={
                "agent_name": agent_name,
                "active_run_id": active_run_id,
                "active_run_status": active_run_status,
                "needs_approval": active_run_status == RUN_STATUS_AWAITING_APPROVAL,
            }
        )


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


class ConversationsListResponse(OffsetPage):
    conversations: list[ConversationRead]
