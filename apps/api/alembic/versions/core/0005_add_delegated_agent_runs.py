"""add delegated agent runs

Revision ID: core_0005
Revises: core_0004
Create Date: 2026-07-02 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0005"
down_revision: str | Sequence[str] | None = "core_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_AGENT_RUN_PARENT = "fk_agent_runs_parent_run_id_agent_runs"


def upgrade() -> None:
    """Apply schema changes."""
    op.add_column("agent_runs", sa.Column("parent_run_id", sa.UUID(), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("delegation_depth", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_foreign_key(
        FK_AGENT_RUN_PARENT,
        "agent_runs",
        "agent_runs",
        ["parent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("agent_runs_trigger_check", "agent_runs", type_="check")
    op.create_check_constraint(
        "agent_runs_trigger_check",
        "agent_runs",
        "trigger IN ('interactive', 'scheduled', 'delegated')",
    )
    op.create_check_constraint(
        "agent_runs_delegation_depth_check",
        "agent_runs",
        "delegation_depth >= 0",
    )
    op.create_index(
        "ix_agent_runs_parent_created",
        "agent_runs",
        ["parent_run_id", "created_at"],
        unique=False,
        postgresql_where=sa.text("parent_run_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index(
        "ix_agent_runs_parent_created",
        table_name="agent_runs",
        postgresql_where=sa.text("parent_run_id IS NOT NULL"),
    )
    op.drop_constraint("agent_runs_delegation_depth_check", "agent_runs", type_="check")
    op.drop_constraint("agent_runs_trigger_check", "agent_runs", type_="check")
    op.create_check_constraint(
        "agent_runs_trigger_check",
        "agent_runs",
        "trigger IN ('interactive', 'scheduled')",
    )
    op.drop_constraint(FK_AGENT_RUN_PARENT, "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "delegation_depth")
    op.drop_column("agent_runs", "parent_run_id")
