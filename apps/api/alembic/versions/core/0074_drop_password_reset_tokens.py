# apps/api/alembic/versions/core/0074_drop_password_reset_tokens.py

"""Drops the password reset token table, which nothing reads or writes.

Revision ID: core_0074
Revises: core_0073
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "core_0074"
down_revision = "core_0073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drops the table and its indexes."""
    op.drop_table("password_reset_tokens")


def downgrade() -> None:
    """Recreates the table as core_0001 created it."""
    op.create_table(
        "password_reset_tokens",
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_password_reset_tokens_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by"], ["users.id"], name="fk_password_reset_tokens_deleted_by_users"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_password_reset_expires_used", "password_reset_tokens", ["expires_at", "used_at"]
    )
    op.create_index(
        "ix_password_reset_user_expires", "password_reset_tokens", ["user_id", "expires_at"]
    )
    op.create_index("ix_password_reset_tokens_deleted_at", "password_reset_tokens", ["deleted_at"])
    op.create_index("ix_password_reset_tokens_expires_at", "password_reset_tokens", ["expires_at"])
    op.create_index(
        "ix_password_reset_tokens_token", "password_reset_tokens", ["token"], unique=True
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
