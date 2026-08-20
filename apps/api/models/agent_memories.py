# apps/api/models/agent_memories.py

"""Long-lived, workspace-scoped agent memories."""

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID

from models.base import Base, TimestampMixin, UUIDMixin


class AgentMemory(Base, UUIDMixin, TimestampMixin):
    """One versioned core memory or searchable note."""

    __tablename__ = "agent_memories"

    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope = Column(String(16), nullable=False)
    agent_id = Column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    kind = Column(String(8), nullable=False, server_default=text("'note'"))
    memory_type = Column(String(16), nullable=False, server_default=text("'fact'"))
    title = Column(String(200), nullable=False)
    content_md = Column(Text, nullable=False)
    embedding = Column(HALFVEC(1024), nullable=True)
    embedding_provider = Column(String(50), nullable=True)
    embedding_model = Column(String(100), nullable=True)
    embedding_dims = Column(Integer, nullable=True)
    content_tsv = Column(
        TSVECTOR,
        Computed("to_tsvector('english', title || ' ' || content_md)", persisted=True),
        nullable=True,
    )
    importance = Column(Integer, nullable=False, server_default=text("3"))
    confidence = Column(Float, nullable=False, server_default=text("0.8"))
    last_reinforced_at = Column(DateTime(timezone=True), nullable=True)
    reinforcement_count = Column(Integer, nullable=False, server_default=text("0"))
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
    access_count = Column(Integer, nullable=False, server_default=text("0"))
    expires_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(16), nullable=False, server_default=text("'active'"))
    superseded_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_memories.id", ondelete="SET NULL"),
        nullable=True,
    )
    archived_at = Column(DateTime(timezone=True), nullable=True)
    archive_reason = Column(String(32), nullable=True)
    source_conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_run_id = Column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    source = Column(String(16), nullable=False)
    created_by = Column(String(8), nullable=False)
    created_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("scope IN ('agent','user','workspace')", name="agent_memories_scope_check"),
        CheckConstraint(
            "(scope = 'agent' AND agent_id IS NOT NULL AND user_id IS NULL) OR "
            "(scope = 'user' AND user_id IS NOT NULL AND agent_id IS NULL) OR "
            "(scope = 'workspace' AND agent_id IS NULL AND user_id IS NULL)",
            name="agent_memories_scope_refs_check",
        ),
        CheckConstraint("kind IN ('core','note')", name="agent_memories_kind_check"),
        CheckConstraint(
            "memory_type IN ('fact','preference','episode','outcome')",
            name="agent_memories_type_check",
        ),
        CheckConstraint(
            "status IN ('active','superseded','archived')",
            name="agent_memories_status_check",
        ),
        CheckConstraint(
            "(status = 'superseded') = (superseded_by_id IS NOT NULL)",
            name="agent_memories_superseded_check",
        ),
        CheckConstraint(
            "(status = 'archived') = (archived_at IS NOT NULL)",
            name="agent_memories_archived_check",
        ),
        CheckConstraint(
            "archive_reason IS NULL OR archive_reason IN ('expired','forgotten','user_deleted')",
            name="agent_memories_archive_reason_check",
        ),
        CheckConstraint("importance BETWEEN 1 AND 5", name="agent_memories_importance_check"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="agent_memories_confidence_check",
        ),
        CheckConstraint(
            "(embedding IS NULL) = (embedding_model IS NULL) AND "
            "(embedding_model IS NULL) = (embedding_provider IS NULL) AND "
            "(embedding_model IS NULL) = (embedding_dims IS NULL)",
            name="agent_memories_embedding_meta_check",
        ),
        CheckConstraint(
            "source IN ('interactive','scheduled','delegated','event','user')",
            name="agent_memories_source_check",
        ),
        CheckConstraint("created_by IN ('agent','user')", name="agent_memories_created_by_check"),
        Index("ix_agent_memories_workspace_scope_status", "workspace_id", "scope", "status"),
        Index(
            "ix_agent_memories_active_core_scope",
            "workspace_id",
            "scope",
            "agent_id",
            "user_id",
            postgresql_where=text("status = 'active' AND kind = 'core'"),
        ),
        Index(
            "ix_agent_memories_active_expiry",
            "expires_at",
            postgresql_where=text("status = 'active' AND expires_at IS NOT NULL"),
        ),
        Index("ix_agent_memories_content_tsv", "content_tsv", postgresql_using="gin"),
        Index(
            "ix_agent_memories_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
        Index("ix_agent_memories_superseded_by_id", "superseded_by_id"),
        Index("ix_agent_memories_source_conversation_id", "source_conversation_id"),
        Index("ix_agent_memories_source_run_id", "source_run_id"),
        Index("ix_agent_memories_workspace_agent", "workspace_id", "agent_id"),
    )
