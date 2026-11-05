# apps/api/alembic/versions/core/0072_add_agent_progress_reviews_enabled.py

"""Adds the agent setting that turns progress reviews at the step limit on or off.

Revision ID: core_0072
Revises: core_0071
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0072"
down_revision = "core_0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Adds the setting, on by default; existing workspace row-level security covers it."""
    op.add_column(
        "agents",
        sa.Column(
            "progress_reviews_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    """Removes the setting."""
    op.drop_column("agents", "progress_reviews_enabled")
