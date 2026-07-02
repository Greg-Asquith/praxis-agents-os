# apps/api/models/conversation.py

"""Conversation and message models for chat history persistence."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from models.base import BaseModel

CONVERSATION_SOURCE_DIRECT = "direct"
CONVERSATION_SOURCE_SCHEDULED = "scheduled"
CONVERSATION_SOURCE_DELEGATED = "delegated"

ALL_CONVERSATION_SOURCES = frozenset(
    {
        CONVERSATION_SOURCE_DIRECT,
        CONVERSATION_SOURCE_SCHEDULED,
        CONVERSATION_SOURCE_DELEGATED,
    }
)


class Conversation(BaseModel):
    """Represents a persisted chat conversation for a user."""

    __tablename__ = "conversations"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="active", server_default=text("'active'"))
    metadata_json = Column("metadata", JSONB, nullable=True)
    unread = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    source = Column(
        String(32),
        nullable=False,
        default=CONVERSATION_SOURCE_DIRECT,
        server_default=text(f"'{CONVERSATION_SOURCE_DIRECT}'"),
    )
    schedule_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_schedules.id", ondelete="SET NULL"),
        nullable=True,
    )
    schedule_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "agent_schedule_runs.id",
            name="fk_conversations_schedule_run_id_agent_schedule_runs",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )

    last_message_at = Column(DateTime(timezone=True), nullable=True)
    active_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)
    agent_slug = Column(String(128), nullable=True, index=True)
    agent_state = Column(JSONB, nullable=True)

    owner = relationship("User", foreign_keys=[user_id], back_populates="conversations")
    creator = relationship("User", foreign_keys=[created_by])
    workspace = relationship("Workspace", foreign_keys=[workspace_id])

    agent = relationship("Agent", foreign_keys=[active_agent_id])
    schedule = relationship("AgentSchedule", foreign_keys=[schedule_id])
    messages = relationship(
        "ConversationMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.sequence",
    )

    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="conversations_status_check"),
        CheckConstraint(
            "source IN ("
            f"'{CONVERSATION_SOURCE_DIRECT}', "
            f"'{CONVERSATION_SOURCE_SCHEDULED}', "
            f"'{CONVERSATION_SOURCE_DELEGATED}'"
            ")",
            name="conversations_source_check",
        ),
        Index("ix_conversations_user_created", "user_id", "created_at"),
        Index("ix_conversations_workspace_created", "workspace_id", "created_at"),
        Index("ix_conversations_last_message", "last_message_at"),
        Index("ix_conversations_unread", "unread"),
        Index(
            "ix_conversations_user_workspace_agent",
            "user_id",
            "workspace_id",
            "agent_slug",
            "created_at",
            postgresql_where=text("deleted = false"),
        ),
        Index(
            "ix_conversations_schedule_id",
            "schedule_id",
            postgresql_where=text("schedule_id IS NOT NULL"),
        ),
        Index(
            "ix_conversations_schedule_run_id",
            "schedule_run_id",
            unique=True,
            postgresql_where=text("schedule_run_id IS NOT NULL"),
        ),
        Index("ix_conversations_source_agent", "source", "agent_slug"),
    )


class ConversationMessage(BaseModel):
    """Represents an individual message within a conversation."""

    __tablename__ = "conversation_messages"

    conversation_id = Column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False, index=True
    )
    role = Column(String(32), nullable=False)
    parts = Column(JSONB, nullable=False)
    metadata_json = Column("metadata", JSONB, nullable=True)
    tool_name = Column(String(128), nullable=True)
    error_json = Column("error", JSONB, nullable=True)
    sequence = Column(BigInteger, nullable=False)
    client_message_id = Column(String(128), nullable=True)

    conversation = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        CheckConstraint(
            "role IN ('system', 'user', 'assistant', 'tool')",
            name="conversation_messages_role_check",
        ),
        Index(
            "ix_conversation_messages_conversation_sequence",
            "conversation_id",
            "sequence",
        ),
        # Unique constraint for idempotency - only enforced when client_message_id is provided
        Index(
            "ix_conversation_messages_client_id",
            "conversation_id",
            "client_message_id",
            unique=True,
            postgresql_where=text("client_message_id IS NOT NULL"),
        ),
    )
