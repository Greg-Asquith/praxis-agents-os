# apps/api/models/ai_usage_event.py

"""Append-only workspace AI usage ledger."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from models.base import Base, CreatedAtMixin, UUIDMixin


class AIUsageEvent(Base, UUIDMixin, CreatedAtMixin):
    """One logical metered AI invocation."""

    __tablename__ = "ai_usage_events"

    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    provider = Column(String(50), nullable=False)
    model = Column(String(128), nullable=False)
    purpose = Column(String(64), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"))
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
    )
    input_tokens = Column(BigInteger, nullable=False, server_default=text("0"))
    cache_read_tokens = Column(BigInteger, nullable=False, server_default=text("0"))
    cache_write_tokens = Column(BigInteger, nullable=False, server_default=text("0"))
    output_tokens = Column(BigInteger, nullable=False, server_default=text("0"))
    requests = Column(BigInteger, nullable=False, server_default=text("0"))
    details = Column(JSONB)

    __table_args__ = (
        CheckConstraint(
            "purpose IN ("
            "'agent_run', 'conversation_naming', 'history_summary', 'kb_annotation', "
            "'web_search', 'web_fetch', 'image_generation', 'embedding_kb_ingest', "
            "'embedding_kb_search', 'embedding_memory_write', "
            "'embedding_memory_search', 'embedding_memory_dedup'"
            ")",
            name="ai_usage_events_purpose_check",
        ),
        CheckConstraint("input_tokens >= 0", name="ai_usage_events_input_tokens_check"),
        CheckConstraint(
            "cache_read_tokens >= 0",
            name="ai_usage_events_cache_read_tokens_check",
        ),
        CheckConstraint(
            "cache_write_tokens >= 0",
            name="ai_usage_events_cache_write_tokens_check",
        ),
        CheckConstraint("output_tokens >= 0", name="ai_usage_events_output_tokens_check"),
        CheckConstraint("requests >= 0", name="ai_usage_events_requests_check"),
        Index("ix_ai_usage_events_workspace_occurred", "workspace_id", "occurred_at"),
    )
