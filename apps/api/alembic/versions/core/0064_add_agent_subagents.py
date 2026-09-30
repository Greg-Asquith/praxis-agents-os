"""Adds the per-agent sub-agents setting, on for built-in agents.

Revision ID: core_0064
Revises: core_0063
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0064"
down_revision = "core_0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "subagents_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.execute("UPDATE agents SET subagents_enabled = true WHERE is_builtin")


def downgrade() -> None:
    op.drop_column("agents", "subagents_enabled")
