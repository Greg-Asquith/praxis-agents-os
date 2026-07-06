# apps/api/models/scratch.py

"""Conversation and run scoped agent scratch entries."""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import text

from models.base import Base, TimestampMixin, UUIDMixin


class ScratchEntry(Base, UUIDMixin, TimestampMixin):
    """Short-lived text scratchpad entry written by an agent run."""

    __tablename__ = "scratch_entries"

    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=True,
    )
    name = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    content_bytes = Column(Integer, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_by_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(conversation_id, run_id) = 1",
            name="scratch_entries_scope_xor_check",
        ),
        CheckConstraint("content_bytes >= 0", name="scratch_entries_content_bytes_check"),
        Index(
            "uq_scratch_conversation_name",
            "conversation_id",
            "name",
            unique=True,
            postgresql_where=text("conversation_id IS NOT NULL"),
        ),
        Index(
            "uq_scratch_run_name",
            "run_id",
            "name",
            unique=True,
            postgresql_where=text("run_id IS NOT NULL"),
        ),
    )
