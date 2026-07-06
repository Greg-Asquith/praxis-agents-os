"""add scratch entries table

Revision ID: core_0012
Revises: core_0011
Create Date: 2026-07-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0012"
down_revision: str | Sequence[str] | None = "core_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        "scratch_entries",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_bytes", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_run_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("content_bytes >= 0", name="scratch_entries_content_bytes_check"),
        sa.CheckConstraint(
            "num_nonnulls(conversation_id, run_id) = 1",
            name="scratch_entries_scope_xor_check",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scratch_entries_workspace_id", "scratch_entries", ["workspace_id"])
    op.create_index("ix_scratch_entries_expires_at", "scratch_entries", ["expires_at"])
    op.create_index(
        "uq_scratch_conversation_name",
        "scratch_entries",
        ["conversation_id", "name"],
        unique=True,
        postgresql_where=sa.text("conversation_id IS NOT NULL"),
    )
    op.create_index(
        "uq_scratch_run_name",
        "scratch_entries",
        ["run_id", "name"],
        unique=True,
        postgresql_where=sa.text("run_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index("uq_scratch_run_name", table_name="scratch_entries")
    op.drop_index("uq_scratch_conversation_name", table_name="scratch_entries")
    op.drop_index("ix_scratch_entries_expires_at", table_name="scratch_entries")
    op.drop_index("ix_scratch_entries_workspace_id", table_name="scratch_entries")
    op.drop_table("scratch_entries")
