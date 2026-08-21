# apps/api/services/conversation_read_contract.py

"""Read contract shared by conversation routes and the stream protocol."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from models.conversation import Conversation

type ConversationSource = Literal["direct", "scheduled", "delegated", "event"]


class ConversationRead(BaseModel):
    id: UUID
    user_id: UUID
    workspace_id: UUID
    created_by: UUID
    title: str | None
    description: str | None
    status: str
    metadata_json: dict[str, Any] | None = Field(serialization_alias="metadata")
    unread: bool
    source: ConversationSource
    last_message_at: datetime | None
    active_agent_id: UUID | None
    agent_slug: str | None
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
        from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL

        read_model = cls.from_conversation(conversation)
        return read_model.model_copy(
            update={
                "agent_name": agent_name,
                "active_run_id": active_run_id,
                "active_run_status": active_run_status,
                "needs_approval": active_run_status == RUN_STATUS_AWAITING_APPROVAL,
            }
        )
