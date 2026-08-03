# apps/api/models/conversation_summary.py

"""Derived summaries for cache-stable conversation history compaction."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from models.base import BaseModel


class ConversationSummary(BaseModel):
    """One bounded automatic summary keyed to a persisted trim watermark."""

    __tablename__ = "conversation_summaries"

    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id"),
        nullable=False,
        index=True,
    )
    watermark_key = Column(
        UUID(as_uuid=True),
        ForeignKey("conversation_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    content = Column(Text, nullable=False)
    source_message_count = Column(Integer, nullable=False)
    model_name = Column(String(255), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "source_message_count >= 0",
            name="ck_conversation_summaries_source_message_count_nonnegative",
        ),
        UniqueConstraint(
            "conversation_id",
            "watermark_key",
            name="uq_conversation_summaries_watermark",
        ),
        Index(
            "ix_conversation_summaries_conversation_created",
            "conversation_id",
            "created_at",
        ),
    )
