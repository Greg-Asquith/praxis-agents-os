# apps/api/models/kb.py

"""Knowledge-base documents and retrieval chunks."""

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID

from models.base import Base, BaseModel, TimestampMixin, UUIDMixin


class KBDocument(BaseModel):
    """Workspace-owned canonical knowledge-base document."""

    __tablename__ = "kb_documents"

    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(String(500), nullable=False)
    concept_id = Column(String(512), nullable=True, index=True)
    source_type = Column(String(32), nullable=False)
    source_updated_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(16), nullable=False, server_default=text("'pending'"))
    processing_error = Column(Text, nullable=True)
    processing_attempts = Column(Integer, nullable=False, server_default=text("0"))
    content_hash = Column(String(64), nullable=False, server_default=text("''"))
    content_md = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    file_revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("file_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    external_id = Column(String(255), nullable=True)
    external_url = Column(Text, nullable=True)
    is_private = Column(Boolean, nullable=False, server_default=text("false"))
    created_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    annotation_enabled = Column(Boolean, nullable=False)
    chunk_count = Column(Integer, nullable=False, server_default=text("0"))
    meta = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    tsv = Column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(summary, ''))",
            persisted=True,
        ),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "source_type IN ('upload','url','manual','conversation','integration')",
            name="ck_kb_documents_source_type",
        ),
        CheckConstraint(
            "status IN ('pending','processing','ready','error')",
            name="ck_kb_documents_status",
        ),
        CheckConstraint(
            "processing_attempts >= 0",
            name="ck_kb_documents_processing_attempts_nonnegative",
        ),
        CheckConstraint("chunk_count >= 0", name="ck_kb_documents_chunk_count_nonnegative"),
        Index("ix_kb_documents_workspace_status", "workspace_id", "status"),
        Index("ix_kb_documents_tsv", "tsv", postgresql_using="gin"),
    )


class KBChunk(Base, UUIDMixin, TimestampMixin):
    """Exact document substring with lexical and semantic retrieval fields."""

    __tablename__ = "kb_chunks"

    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("kb_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    context_line = Column(Text, nullable=True)
    char_start = Column(Integer, nullable=False)
    char_end = Column(Integer, nullable=False)
    token_estimate = Column(Integer, nullable=False)
    embedding = Column(HALFVEC(1024), nullable=True)
    embedding_provider = Column(String(32), nullable=True)
    embedding_model = Column(String(128), nullable=True)
    embedding_dims = Column(Integer, nullable=True)
    tsv = Column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(context_line, '') || ' ' || content)",
            persisted=True,
        ),
        nullable=True,
    )
    meta = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    __table_args__ = (
        CheckConstraint("char_end > char_start", name="ck_kb_chunks_char_range"),
        CheckConstraint("token_estimate >= 0", name="ck_kb_chunks_token_estimate_nonnegative"),
        CheckConstraint(
            "("
            "embedding IS NULL AND embedding_provider IS NULL "
            "AND embedding_model IS NULL AND embedding_dims IS NULL"
            ") OR ("
            "embedding IS NOT NULL AND embedding_provider IS NOT NULL "
            "AND embedding_model IS NOT NULL AND embedding_dims IS NOT NULL"
            ")",
            name="ck_kb_chunks_embedding_metadata_all_or_none",
        ),
        UniqueConstraint("document_id", "chunk_index", name="uq_kb_chunks_document_index"),
        Index(
            "ix_kb_chunks_document_pending_embedding",
            "document_id",
            postgresql_where=text("embedding IS NULL"),
        ),
        Index("ix_kb_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_kb_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )
