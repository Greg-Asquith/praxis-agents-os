"""Drops the per-agent Code Mode flag; every agent can run workflows.

Revision ID: core_0062
Revises: core_0061
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0062"
down_revision = "core_0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("agents", "code_mode_enabled")


def downgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "code_mode_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
