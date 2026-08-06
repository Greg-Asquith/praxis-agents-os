"""expand agent run completion evidence

Revision ID: core_0036
Revises: core_0035
Create Date: 2026-08-06 00:00:01.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "core_0036"
down_revision: str | Sequence[str] | None = "core_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow every schema-valid completion report within the evidence column."""
    op.drop_constraint(
        "agent_runs_completion_json_size_check",
        "agent_runs",
        type_="check",
    )
    op.create_check_constraint(
        "agent_runs_completion_json_size_check",
        "agent_runs",
        "completion_json IS NULL OR octet_length(completion_json::text) <= 73728",
    )


def downgrade() -> None:
    """Restore the original completion evidence bound."""
    op.drop_constraint(
        "agent_runs_completion_json_size_check",
        "agent_runs",
        type_="check",
    )
    op.create_check_constraint(
        "agent_runs_completion_json_size_check",
        "agent_runs",
        "completion_json IS NULL OR octet_length(completion_json::text) <= 16384",
    )
