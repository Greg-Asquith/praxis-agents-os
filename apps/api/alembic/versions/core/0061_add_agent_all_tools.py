"""Adds the all-tools selection mode to agents.

Revision ID: core_0061
Revises: core_0060
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "core_0061"
down_revision = "core_0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("all_tools", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "agents",
        sa.Column(
            "excluded_tool_names",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "excluded_tool_names")
    op.drop_column("agents", "all_tools")
