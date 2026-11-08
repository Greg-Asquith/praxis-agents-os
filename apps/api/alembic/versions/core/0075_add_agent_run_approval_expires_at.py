# apps/api/alembic/versions/core/0075_add_agent_run_approval_expires_at.py

"""Gives the approval deadline its own column and ties approval metadata to status.

Revision ID: core_0075
Revises: core_0074
"""

import sqlalchemy as sa

from alembic import op
from core.settings import settings

revision = "core_0075"
down_revision = "core_0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Adds the deadline, backfills waiting runs, and adds the status checks."""
    op.add_column(
        "agent_runs",
        sa.Column("approval_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    if settings.AGENT_RUN_APPROVAL_EXPIRY_DAYS > 0:
        op.execute(
            sa.text(
                "UPDATE agent_runs SET approval_expires_at = updated_at + make_interval(days => :days) "
                "WHERE status = 'awaiting_approval'"
            ).bindparams(days=settings.AGENT_RUN_APPROVAL_EXPIRY_DAYS)
        )
    # A reservation left on a run that stopped running can never be used, so drop it.
    op.execute(
        "UPDATE agent_runs SET metadata = metadata - 'approval_continuation' "
        "WHERE status <> 'running' AND metadata ? 'approval_continuation'"
    )
    op.create_check_constraint(
        "agent_runs_approval_expires_at_check",
        "agent_runs",
        "approval_expires_at IS NULL OR status = 'awaiting_approval'",
    )
    op.create_check_constraint(
        "agent_runs_approval_continuation_check",
        "agent_runs",
        "metadata IS NULL OR NOT (metadata ? 'approval_continuation') OR status = 'running'",
    )
    op.create_index(
        "ix_agent_runs_approval_expiry",
        "agent_runs",
        ["approval_expires_at"],
        postgresql_where=sa.text("deleted = false AND status = 'awaiting_approval'"),
    )


def downgrade() -> None:
    """Removes the deadline column and its checks."""
    op.drop_index("ix_agent_runs_approval_expiry", table_name="agent_runs")
    op.drop_constraint("agent_runs_approval_continuation_check", "agent_runs", type_="check")
    op.drop_constraint("agent_runs_approval_expires_at_check", "agent_runs", type_="check")
    op.drop_column("agent_runs", "approval_expires_at")
