"""create app schema

Revision ID: app_0001
Revises:
Create Date: 2026-06-26 09:35:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "app_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("app",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.execute("CREATE SCHEMA IF NOT EXISTS app")


def downgrade() -> None:
    """Revert schema changes."""
    op.execute("DROP SCHEMA IF EXISTS app")
