"""Adds deliberate workspace conversation sharing.

Revision ID: core_0053
Revises: core_0052
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "core_0053"
down_revision = "core_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Adds private defaults without changing workspace row-level security."""
    op.add_column(
        "conversations",
        sa.Column("visibility", sa.String(16), nullable=False, server_default="private"),
    )
    op.add_column(
        "conversations", sa.Column("shared_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "conversations",
        sa.Column("shared_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_conversations_shared_by_user_id_users",
        "conversations",
        "users",
        ["shared_by_user_id"],
        ["id"],
    )
    op.create_check_constraint(
        "conversations_visibility_check", "conversations", "visibility IN ('private', 'workspace')"
    )
    op.create_check_constraint(
        "conversations_child_private_check",
        "conversations",
        "source != 'delegated' OR visibility = 'private'",
    )

    op.create_index(
        "ix_conversations_workspace_shared",
        "conversations",
        [
            "workspace_id",
            sa.text("coalesce(last_message_at, created_at) DESC"),
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
        postgresql_where=sa.text(
            "visibility = 'workspace' AND deleted = false AND source != 'delegated'"
        ),
    )


def downgrade() -> None:
    """Removes workspace sharing state."""
    op.drop_index("ix_conversations_workspace_shared", table_name="conversations")
    op.drop_constraint("conversations_child_private_check", "conversations", type_="check")
    op.drop_constraint("conversations_visibility_check", "conversations", type_="check")
    op.drop_constraint(
        "fk_conversations_shared_by_user_id_users", "conversations", type_="foreignkey"
    )
    op.drop_column("conversations", "shared_by_user_id")
    op.drop_column("conversations", "shared_at")
    op.drop_column("conversations", "visibility")
