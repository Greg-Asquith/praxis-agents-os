"""add conversation summaries

Revision ID: core_0021
Revises: core_0020
Create Date: 2026-07-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0021"
down_revision: str | Sequence[str] | None = "core_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        "conversation_summaries",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("watermark_key", sa.UUID(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_message_count", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
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
        sa.CheckConstraint(
            "source_message_count >= 0",
            name="ck_conversation_summaries_source_message_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["watermark_key"],
            ["conversation_messages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "watermark_key",
            name="uq_conversation_summaries_watermark",
        ),
    )
    op.create_index(
        "ix_conversation_summaries_conversation_id",
        "conversation_summaries",
        ["conversation_id"],
    )
    op.create_index(
        "ix_conversation_summaries_conversation_created",
        "conversation_summaries",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_conversation_summaries_deleted_at",
        "conversation_summaries",
        ["deleted_at"],
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index(
        "ix_conversation_summaries_deleted_at",
        table_name="conversation_summaries",
        if_exists=True,
    )
    op.drop_index(
        "ix_conversation_summaries_conversation_created",
        table_name="conversation_summaries",
    )
    op.drop_index(
        "ix_conversation_summaries_conversation_id",
        table_name="conversation_summaries",
    )
    op.drop_table("conversation_summaries")
