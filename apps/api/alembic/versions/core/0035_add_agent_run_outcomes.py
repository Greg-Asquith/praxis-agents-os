"""add agent run outcomes

Revision ID: core_0035
Revises: core_0034
Create Date: 2026-08-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

AGENT_RUN_OUTCOME_BACKFILL_SQL = """
UPDATE agent_runs
SET outcome = CASE
    WHEN status = 'completed' THEN 'success'
    WHEN status = 'cancelled' THEN 'cancelled'
    WHEN error_code = 'approval_expired' THEN 'blocked'
    WHEN error_code = 'usage_limit_exceeded' THEN 'budget_exhausted'
    ELSE 'error'
END,
completion_json = CASE
    WHEN status = 'failed'
        THEN jsonb_build_object('error_code', COALESCE(error_code, 'agent_run_failed'))
    ELSE NULL
END
WHERE status IN ('completed', 'failed', 'cancelled')
  AND outcome IS NULL
"""

revision: str = "core_0035"
down_revision: str | Sequence[str] | None = "core_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add bounded terminal verdict evidence and backfill existing terminal runs."""
    op.add_column("agent_runs", sa.Column("outcome", sa.String(length=32), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("completion_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        "agent_runs_outcome_check",
        "agent_runs",
        "outcome IS NULL OR outcome IN ("
        "'success', 'gate_failed', 'budget_exhausted', 'blocked', 'error', 'cancelled'"
        ")",
    )
    op.create_check_constraint(
        "agent_runs_completion_json_size_check",
        "agent_runs",
        "completion_json IS NULL OR octet_length(completion_json::text) <= 16384",
    )
    op.execute(AGENT_RUN_OUTCOME_BACKFILL_SQL)


def downgrade() -> None:
    """Remove terminal verdict evidence."""
    op.drop_constraint(
        "agent_runs_completion_json_size_check",
        "agent_runs",
        type_="check",
    )
    op.drop_constraint("agent_runs_outcome_check", "agent_runs", type_="check")
    op.drop_column("agent_runs", "completion_json")
    op.drop_column("agent_runs", "outcome")
