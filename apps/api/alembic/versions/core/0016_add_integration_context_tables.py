"""add integration context tables

Revision ID: core_0016
Revises: core_0015
Create Date: 2026-07-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0016"
down_revision: str | Sequence[str] | None = "core_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        "integration_context_groups",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
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
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_integration_context_groups_workspace_id",
        "integration_context_groups",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_integration_context_groups_deleted_at",
        "integration_context_groups",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        "uq_integration_context_groups_workspace_name",
        "integration_context_groups",
        ["workspace_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted = false"),
    )

    op.create_table(
        "integration_context_group_members",
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("integration_resource_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["group_id"], ["integration_context_groups.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["integration_resource_id"], ["integration_resources.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "group_id",
            "integration_resource_id",
            name="uq_integration_context_group_members_resource",
        ),
    )
    op.create_index(
        "ix_integration_context_group_members_group_id",
        "integration_context_group_members",
        ["group_id"],
        unique=False,
    )
    op.create_index(
        "ix_integration_context_group_members_integration_resource_id",
        "integration_context_group_members",
        ["integration_resource_id"],
        unique=False,
    )

    op.create_table(
        "active_context_selections",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("integration_resource_id", sa.UUID(), nullable=True),
        sa.Column("context_group_id", sa.UUID(), nullable=True),
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
        sa.CheckConstraint(
            "num_nonnulls(integration_resource_id, context_group_id) = 1",
            name="active_context_selections_target_check",
        ),
        sa.ForeignKeyConstraint(
            ["context_group_id"], ["integration_context_groups.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["integration_resource_id"], ["integration_resources.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            name="uq_active_context_selections_conversation",
        ),
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_table("active_context_selections")
    op.drop_index(
        "ix_integration_context_group_members_integration_resource_id",
        table_name="integration_context_group_members",
    )
    op.drop_index(
        "ix_integration_context_group_members_group_id",
        table_name="integration_context_group_members",
    )
    op.drop_table("integration_context_group_members")
    op.drop_index(
        "uq_integration_context_groups_workspace_name",
        table_name="integration_context_groups",
        postgresql_where=sa.text("deleted = false"),
    )
    op.drop_index(
        "ix_integration_context_groups_deleted_at",
        table_name="integration_context_groups",
    )
    op.drop_index(
        "ix_integration_context_groups_workspace_id",
        table_name="integration_context_groups",
    )
    op.drop_table("integration_context_groups")
