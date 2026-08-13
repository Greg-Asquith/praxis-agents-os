"""Add the per-agent code-mode enablement flag.

Revision ID: core_0040
Revises: core_0039
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0040"
down_revision = "core_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "code_mode_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "code_mode_enabled")
