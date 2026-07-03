# apps/api/models/conversation_todos.py

"""Conversation-scoped planning scratchpad for runtime agents."""

from sqlalchemy import Column, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.base import BaseModel


class ConversationTodoList(BaseModel):
    """One durable todo list owned by a conversation."""

    __tablename__ = "conversation_todos"

    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    items = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    updated_by_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_conversation_todos_conversation_id"),
        Index("ix_conversation_todos_workspace_updated", "workspace_id", "updated_at"),
    )
