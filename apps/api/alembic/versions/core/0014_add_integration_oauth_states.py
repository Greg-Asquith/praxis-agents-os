"""add integration OAuth states

Revision ID: core_0014
Revises: core_0013
Create Date: 2026-07-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0014"
down_revision: str | Sequence[str] | None = "core_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        "integration_oauth_states",
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("code_verifier_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["connection_id"], ["integration_connections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("jti"),
    )
    op.create_index(
        "ix_integration_oauth_states_connection_id",
        "integration_oauth_states",
        ["connection_id"],
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index(
        "ix_integration_oauth_states_connection_id",
        table_name="integration_oauth_states",
    )
    op.drop_table("integration_oauth_states")
