"""add agent schedule names

Revision ID: core_0015
Revises: core_0014
Create Date: 2026-07-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0015"
down_revision: str | Sequence[str] | None = "core_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.add_column(
        "agent_schedules",
        sa.Column("name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_column("agent_schedules", "name")
