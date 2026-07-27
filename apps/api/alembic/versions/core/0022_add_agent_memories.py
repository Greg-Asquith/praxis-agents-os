"""add agent memories

Revision ID: core_0022
Revises: core_0021
Create Date: 2026-07-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import HALFVEC
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "core_0022"
down_revision: str | Sequence[str] | None = "core_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        "agent_memories",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=8), server_default=sa.text("'note'"), nullable=False),
        sa.Column(
            "memory_type",
            sa.String(length=16),
            server_default=sa.text("'fact'"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("embedding", HALFVEC(dim=1024), nullable=True),
        sa.Column("embedding_provider", sa.String(length=50), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
        sa.Column("embedding_dims", sa.Integer(), nullable=True),
        sa.Column(
            "content_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english', title || ' ' || content_md)",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("importance", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("confidence", sa.Float(), server_default=sa.text("0.8"), nullable=False),
        sa.Column("last_reinforced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reinforcement_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("superseded_by_id", sa.UUID(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archive_reason", sa.String(length=32), nullable=True),
        sa.Column("source_conversation_id", sa.UUID(), nullable=True),
        sa.Column("source_run_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=8), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
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
        sa.CheckConstraint(
            "archive_reason IS NULL OR archive_reason IN ('expired','forgotten','user_deleted')",
            name="agent_memories_archive_reason_check",
        ),
        sa.CheckConstraint(
            "(status = 'archived') = (archived_at IS NOT NULL)",
            name="agent_memories_archived_check",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="agent_memories_confidence_check",
        ),
        sa.CheckConstraint(
            "created_by IN ('agent','user')",
            name="agent_memories_created_by_check",
        ),
        sa.CheckConstraint(
            "(embedding IS NULL) = (embedding_model IS NULL) AND "
            "(embedding_model IS NULL) = (embedding_provider IS NULL) AND "
            "(embedding_model IS NULL) = (embedding_dims IS NULL)",
            name="agent_memories_embedding_meta_check",
        ),
        sa.CheckConstraint(
            "importance BETWEEN 1 AND 5",
            name="agent_memories_importance_check",
        ),
        sa.CheckConstraint("kind IN ('core','note')", name="agent_memories_kind_check"),
        sa.CheckConstraint(
            "(scope = 'agent' AND agent_id IS NOT NULL AND user_id IS NULL) OR "
            "(scope = 'user' AND user_id IS NOT NULL AND agent_id IS NULL) OR "
            "(scope = 'workspace' AND agent_id IS NULL AND user_id IS NULL)",
            name="agent_memories_scope_refs_check",
        ),
        sa.CheckConstraint(
            "scope IN ('agent','user','workspace')",
            name="agent_memories_scope_check",
        ),
        sa.CheckConstraint(
            "source IN ('interactive','scheduled','delegated','event','user')",
            name="agent_memories_source_check",
        ),
        sa.CheckConstraint(
            "status IN ('active','superseded','archived')",
            name="agent_memories_status_check",
        ),
        sa.CheckConstraint(
            "(status = 'superseded') = (superseded_by_id IS NOT NULL)",
            name="agent_memories_superseded_check",
        ),
        sa.CheckConstraint(
            "memory_type IN ('fact','preference','episode','outcome')",
            name="agent_memories_type_check",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["source_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["agent_memories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_memories_workspace_id", "agent_memories", ["workspace_id"])
    op.create_index(
        "ix_agent_memories_workspace_scope_status",
        "agent_memories",
        ["workspace_id", "scope", "status"],
    )
    op.create_index(
        "ix_agent_memories_active_core_scope",
        "agent_memories",
        ["workspace_id", "scope", "agent_id", "user_id"],
        postgresql_where=sa.text("status = 'active' AND kind = 'core'"),
    )
    op.create_index(
        "ix_agent_memories_active_expiry",
        "agent_memories",
        ["expires_at"],
        postgresql_where=sa.text("status = 'active' AND expires_at IS NOT NULL"),
    )
    op.create_index(
        "ix_agent_memories_content_tsv",
        "agent_memories",
        ["content_tsv"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_agent_memories_embedding_hnsw",
        "agent_memories",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
        postgresql_with={"m": "16", "ef_construction": "64"},
    )
    op.create_index(
        "ix_agent_memories_superseded_by_id",
        "agent_memories",
        ["superseded_by_id"],
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index("ix_agent_memories_superseded_by_id", table_name="agent_memories")
    op.drop_index("ix_agent_memories_embedding_hnsw", table_name="agent_memories")
    op.drop_index("ix_agent_memories_content_tsv", table_name="agent_memories")
    op.drop_index("ix_agent_memories_active_expiry", table_name="agent_memories")
    op.drop_index("ix_agent_memories_active_core_scope", table_name="agent_memories")
    op.drop_index("ix_agent_memories_workspace_scope_status", table_name="agent_memories")
    op.drop_index("ix_agent_memories_workspace_id", table_name="agent_memories")
    op.drop_table("agent_memories")
