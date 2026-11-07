# apps/api/alembic/versions/core/0073_add_job_lease_token.py

"""Fences job leases per attempt and drops the unwritten cancelled status.

Revision ID: core_0073
Revises: core_0072
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "core_0073"
down_revision = "core_0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Adds the per-claim lease token and narrows the status constraint."""
    op.add_column(
        "jobs",
        sa.Column(
            "lease_token",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.drop_constraint("jobs_status_check", "jobs", type_="check")
    op.create_check_constraint(
        "jobs_status_check",
        "jobs",
        "status IN ('pending', 'running', 'succeeded', 'failed')",
    )


def downgrade() -> None:
    """Restores the previous status constraint and removes the token."""
    op.drop_constraint("jobs_status_check", "jobs", type_="check")
    op.create_check_constraint(
        "jobs_status_check",
        "jobs",
        "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
    )
    op.drop_column("jobs", "lease_token")
