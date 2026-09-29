"""Adds workspace tool policies and the workspace default model.

Revision ID: core_0060
Revises: core_0059
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0060"
down_revision = "core_0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("default_model_provider", sa.String(50), nullable=True))
    op.add_column("workspaces", sa.Column("default_model", sa.String(100), nullable=True))
    op.create_check_constraint(
        "ck_workspaces_default_model_pair",
        "workspaces",
        "(default_model_provider IS NULL) = (default_model IS NULL)",
    )
    op.add_column("workspace_tool_settings", sa.Column("policy", sa.String(20), nullable=True))
    op.create_check_constraint(
        "ck_workspace_tool_settings_policy",
        "workspace_tool_settings",
        "policy IS NULL OR policy IN ('auto', 'approval')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_workspace_tool_settings_policy", "workspace_tool_settings", type_="check"
    )
    op.drop_column("workspace_tool_settings", "policy")
    op.drop_constraint("ck_workspaces_default_model_pair", "workspaces", type_="check")
    op.drop_column("workspaces", "default_model")
    op.drop_column("workspaces", "default_model_provider")
