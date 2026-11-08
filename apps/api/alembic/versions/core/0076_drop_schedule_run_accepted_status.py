# apps/api/alembic/versions/core/0076_drop_schedule_run_accepted_status.py

"""Removes the unwritten 'accepted' schedule run status.

Revision ID: core_0076
Revises: core_0075
"""

from alembic import op

revision = "core_0076"
down_revision = "core_0075"
branch_labels = None
depends_on = None

_TABLE = "agent_schedule_runs"
_CONSTRAINT = "agent_schedule_runs_status_check"
_STATUSES = (
    "'pending', 'claimed', 'running', 'awaiting_approval', "
    "'completed', 'retryable_failed', 'terminal_failed', 'cancelled'"
)


def upgrade() -> None:
    """Narrows the status check to the states the scheduler writes."""
    op.execute(f"UPDATE {_TABLE} SET status = 'running' WHERE status = 'accepted'")
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, f"status IN ({_STATUSES})")


def downgrade() -> None:
    """Allows 'accepted' again."""
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, f"status IN ('accepted', {_STATUSES})")
