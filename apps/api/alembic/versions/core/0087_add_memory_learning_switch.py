# apps/api/alembic/versions/core/0087_add_memory_learning_switch.py

"""Adds the workspace switch for learning memories from finished conversations.

Revision ID: core_0087
Revises: core_0086
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0087"
down_revision = "core_0086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "memory_learning_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "memory_learning_enabled")
