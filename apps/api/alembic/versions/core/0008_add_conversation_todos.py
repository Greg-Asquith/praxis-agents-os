"""add conversation todos

Revision ID: core_0008
Revises: core_0007
Create Date: 2026-07-03 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "core_0008"
down_revision: str | Sequence[str] | None = "core_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        "conversation_todos",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column(
            "items",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("updated_by_run_id", sa.UUID(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["updated_by_run_id"],
            ["agent_runs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            name="uq_conversation_todos_conversation_id",
        ),
    )
    op.create_index(
        "ix_conversation_todos_conversation_id",
        "conversation_todos",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_conversation_todos_deleted_at",
        "conversation_todos",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        "ix_conversation_todos_workspace_id",
        "conversation_todos",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_conversation_todos_workspace_updated",
        "conversation_todos",
        ["workspace_id", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index(
        "ix_conversation_todos_workspace_updated",
        table_name="conversation_todos",
    )
    op.drop_index("ix_conversation_todos_workspace_id", table_name="conversation_todos")
    op.drop_index("ix_conversation_todos_deleted_at", table_name="conversation_todos")
    op.drop_index("ix_conversation_todos_conversation_id", table_name="conversation_todos")
    op.drop_table("conversation_todos")
