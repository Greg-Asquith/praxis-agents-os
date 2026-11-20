# apps/api/alembic/versions/core/0085_add_memory_recall_controls.py

"""Adds the controls that stop memories coming up in a turn automatically.

Revision ID: core_0085
Revises: core_0084
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0085"
down_revision = "core_0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_memories",
        sa.Column("recall_disabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "memory_recall_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "memory_recall_enabled")
    op.drop_column("agent_memories", "recall_disabled_at")
