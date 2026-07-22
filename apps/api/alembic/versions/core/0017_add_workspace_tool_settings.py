"""add workspace tool settings

Revision ID: core_0017
Revises: core_0016
Create Date: 2026-07-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0017"
down_revision: str | Sequence[str] | None = "core_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        "workspace_tool_settings",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "tool_name",
            name="uq_workspace_tool_settings_workspace_tool",
        ),
    )
    op.create_index(
        "ix_workspace_tool_settings_workspace_id",
        "workspace_tool_settings",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_tool_settings_workspace_enabled",
        "workspace_tool_settings",
        ["workspace_id", "enabled"],
        unique=False,
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index(
        "ix_workspace_tool_settings_workspace_enabled",
        table_name="workspace_tool_settings",
    )
    op.drop_index(
        "ix_workspace_tool_settings_workspace_id",
        table_name="workspace_tool_settings",
    )
    op.drop_table("workspace_tool_settings")
