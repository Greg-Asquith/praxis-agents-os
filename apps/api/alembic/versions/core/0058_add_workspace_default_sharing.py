"""Adds the workspace default audience for conversations.

Revision ID: core_0058
Revises: core_0057
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0058"
down_revision = "core_0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "conversations_shared_by_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "conversations_shared_by_default")
