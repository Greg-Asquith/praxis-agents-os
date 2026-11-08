# apps/api/alembic/versions/core/0077_pin_delegation_depth.py

"""Pins delegated runs to one level and ties depth to the parent link.

Revision ID: core_0077
Revises: core_0076
"""

from alembic import op

revision = "core_0077"
down_revision = "core_0076"
branch_labels = None
depends_on = None

_TABLE = "agent_runs"
_DEPTH_CHECK = "agent_runs_delegation_depth_check"
_PARENT_CHECK = "agent_runs_delegation_parent_check"
_PARENT_FK = "fk_agent_runs_parent_run_id_agent_runs"


def _replace_parent_fk(ondelete: str) -> None:
    op.drop_constraint(_PARENT_FK, _TABLE, type_="foreignkey")
    op.create_foreign_key(_PARENT_FK, _TABLE, _TABLE, ["parent_run_id"], ["id"], ondelete=ondelete)


def upgrade() -> None:
    """Allows depth 0 for root runs and depth 1 for runs with a parent."""
    # Runs whose parent was deleted become roots; any deeper chain becomes one level.
    op.execute(f"UPDATE {_TABLE} SET delegation_depth = 0 WHERE parent_run_id IS NULL")
    op.execute(f"UPDATE {_TABLE} SET delegation_depth = 1 WHERE parent_run_id IS NOT NULL")
    op.drop_constraint(_DEPTH_CHECK, _TABLE, type_="check")
    op.create_check_constraint(_DEPTH_CHECK, _TABLE, "delegation_depth IN (0, 1)")
    op.create_check_constraint(
        _PARENT_CHECK, _TABLE, "(parent_run_id IS NULL) = (delegation_depth = 0)"
    )
    # A child can't outlive its parent once the parent link is required for depth 1.
    _replace_parent_fk("CASCADE")


def downgrade() -> None:
    """Restores the non-negative depth check and the nullable parent link."""
    _replace_parent_fk("SET NULL")
    op.drop_constraint(_PARENT_CHECK, _TABLE, type_="check")
    op.drop_constraint(_DEPTH_CHECK, _TABLE, type_="check")
    op.create_check_constraint(_DEPTH_CHECK, _TABLE, "delegation_depth >= 0")
