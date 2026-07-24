# apps/api/alembic/versions/core/0020_add_kb_documents_and_chunks.py

"""add knowledge-base documents and chunks

Revision ID: core_0020
Revises: core_0019
Create Date: 2026-07-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import HALFVEC
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "core_0020"
down_revision: str | Sequence[str] | None = "core_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        "kb_documents",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("concept_id", sa.String(length=512), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column(
            "processing_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "content_hash", sa.String(length=64), server_default=sa.text("''"), nullable=False
        ),
        sa.Column("content_md", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("file_revision_id", sa.UUID(), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("is_private", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("annotation_enabled", sa.Boolean(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(summary, ''))",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.UUID(), nullable=True),
        sa.CheckConstraint("chunk_count >= 0", name="ck_kb_documents_chunk_count_nonnegative"),
        sa.CheckConstraint(
            "processing_attempts >= 0",
            name="ck_kb_documents_processing_attempts_nonnegative",
        ),
        sa.CheckConstraint(
            "source_type IN ('upload','url','manual','conversation','integration')",
            name="ck_kb_documents_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending','processing','ready','error')",
            name="ck_kb_documents_status",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["file_revision_id"],
            ["file_revisions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kb_documents_concept_id", "kb_documents", ["concept_id"])
    op.create_index("ix_kb_documents_deleted_at", "kb_documents", ["deleted_at"])
    op.create_index("ix_kb_documents_workspace_id", "kb_documents", ["workspace_id"])
    op.create_index(
        "ix_kb_documents_workspace_status",
        "kb_documents",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_kb_documents_tsv",
        "kb_documents",
        ["tsv"],
        postgresql_using="gin",
    )

    op.create_table(
        "kb_chunks",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("context_line", sa.Text(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("embedding", HALFVEC(dim=1024), nullable=True),
        sa.Column("embedding_provider", sa.String(length=32), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        sa.Column("embedding_dims", sa.Integer(), nullable=True),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english', coalesce(context_line, '') || ' ' || content)",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("char_end > char_start", name="ck_kb_chunks_char_range"),
        sa.CheckConstraint(
            "("
            "embedding IS NULL AND embedding_provider IS NULL "
            "AND embedding_model IS NULL AND embedding_dims IS NULL"
            ") OR ("
            "embedding IS NOT NULL AND embedding_provider IS NOT NULL "
            "AND embedding_model IS NOT NULL AND embedding_dims IS NOT NULL"
            ")",
            name="ck_kb_chunks_embedding_metadata_all_or_none",
        ),
        sa.CheckConstraint(
            "token_estimate >= 0",
            name="ck_kb_chunks_token_estimate_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["kb_documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_kb_chunks_document_index",
        ),
    )
    op.create_index("ix_kb_chunks_workspace_id", "kb_chunks", ["workspace_id"])
    op.create_index(
        "ix_kb_chunks_document_pending_embedding",
        "kb_chunks",
        ["document_id"],
        postgresql_where=sa.text("embedding IS NULL"),
    )
    op.create_index(
        "ix_kb_chunks_tsv",
        "kb_chunks",
        ["tsv"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_kb_chunks_embedding_hnsw",
        "kb_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
        postgresql_with={"m": "16", "ef_construction": "64"},
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index("ix_kb_chunks_embedding_hnsw", table_name="kb_chunks")
    op.drop_index("ix_kb_chunks_tsv", table_name="kb_chunks")
    op.drop_index("ix_kb_chunks_document_pending_embedding", table_name="kb_chunks")
    op.drop_index("ix_kb_chunks_workspace_id", table_name="kb_chunks")
    op.drop_table("kb_chunks")

    op.drop_index("ix_kb_documents_tsv", table_name="kb_documents")
    op.drop_index("ix_kb_documents_workspace_status", table_name="kb_documents")
    op.drop_index("ix_kb_documents_workspace_id", table_name="kb_documents")
    op.drop_index("ix_kb_documents_deleted_at", table_name="kb_documents")
    op.drop_index("ix_kb_documents_concept_id", table_name="kb_documents")
    op.drop_table("kb_documents")
