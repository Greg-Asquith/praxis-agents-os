"""add agent run leases

Revision ID: core_0003
Revises: core_0002
Create Date: 2026-06-30 18:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0003"
down_revision: str | Sequence[str] | None = "core_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.add_column(
        "agent_runs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("owner_instance_id", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_agent_runs_lease_expiry",
        "agent_runs",
        ["lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("deleted = false AND status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index(
        "ix_agent_runs_lease_expiry",
        table_name="agent_runs",
        postgresql_where=sa.text("deleted = false AND status IN ('pending', 'running')"),
    )
    op.drop_column("agent_runs", "owner_instance_id")
    op.drop_column("agent_runs", "lease_expires_at")
