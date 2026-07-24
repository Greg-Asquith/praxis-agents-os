# apps/api/alembic/versions/core/0019_add_embedding_token_usage.py

"""add embedding token usage table

Revision ID: core_0019
Revises: core_0018
Create Date: 2026-07-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0019"
down_revision: str | Sequence[str] | None = "core_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        "embedding_token_usage",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("tokens_used", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
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
            "tokens_used >= 0",
            name="ck_embedding_token_usage_tokens_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "period_month",
            name="uq_embedding_token_usage_workspace_month",
        ),
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_table("embedding_token_usage")
