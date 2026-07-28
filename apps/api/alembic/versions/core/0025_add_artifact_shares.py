# apps/api/alembic/versions/core/0025_add_artifact_shares.py

"""add version-pinned artifact shares

Revision ID: core_0025
Revises: core_0024
Create Date: 2026-07-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0025"
down_revision: str | Sequence[str] | None = "core_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifact_shares",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=8), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("revoked_by_user_id", sa.UUID(), nullable=True),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
            "access_count >= 0",
            name="artifact_shares_access_count_check",
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["artifact_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_artifact_shares_artifact_id", "artifact_shares", ["artifact_id"])
    op.create_index("ix_artifact_shares_expires_at", "artifact_shares", ["expires_at"])
    op.create_index("ix_artifact_shares_workspace_id", "artifact_shares", ["workspace_id"])
    op.create_index(
        "ix_artifact_shares_workspace_created",
        "artifact_shares",
        ["workspace_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_artifact_shares_workspace_created", table_name="artifact_shares")
    op.drop_index("ix_artifact_shares_workspace_id", table_name="artifact_shares")
    op.drop_index("ix_artifact_shares_expires_at", table_name="artifact_shares")
    op.drop_index("ix_artifact_shares_artifact_id", table_name="artifact_shares")
    op.drop_table("artifact_shares")
