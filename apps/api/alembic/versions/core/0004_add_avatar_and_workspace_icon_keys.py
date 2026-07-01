"""add avatar and workspace icon object keys

Revision ID: core_0004
Revises: core_0003
Create Date: 2026-07-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0004"
down_revision: str | Sequence[str] | None = "core_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.add_column("users", sa.Column("avatar_object_key", sa.String(), nullable=True))
    op.add_column("workspaces", sa.Column("icon_object_key", sa.String(), nullable=True))


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_column("workspaces", "icon_object_key")
    op.drop_column("users", "avatar_object_key")
