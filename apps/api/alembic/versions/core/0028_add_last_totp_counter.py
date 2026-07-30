"""track the last accepted login TOTP counter

Revision ID: core_0028
Revises: core_0027
Create Date: 2026-07-30 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0028"
down_revision: str | Sequence[str] | None = "core_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.add_column("users", sa.Column("last_totp_counter", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_column("users", "last_totp_counter")
