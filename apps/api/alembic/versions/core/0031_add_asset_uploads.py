"""add replay-safe asset upload grants

Revision ID: core_0031
Revises: core_0030
Create Date: 2026-07-31 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "core_0031"
down_revision: str | Sequence[str] | None = "core_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        "asset_uploads",
        sa.Column("token_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_asset_uploads_object_key"),
        sa.UniqueConstraint("token_id", name="uq_asset_uploads_token_id"),
    )
    op.create_index(
        "ix_asset_uploads_pending_expiry",
        "asset_uploads",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("consumed_at IS NULL"),
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index("ix_asset_uploads_pending_expiry", table_name="asset_uploads")
    op.drop_table("asset_uploads")
