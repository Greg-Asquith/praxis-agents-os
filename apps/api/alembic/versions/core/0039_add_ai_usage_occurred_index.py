"""Add the platform AI usage time-range index.

Revision ID: core_0039
Revises: core_0038
"""

from alembic import op

revision = "core_0039"
down_revision = "core_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_ai_usage_events_occurred_at",
        "ai_usage_events",
        ["occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_usage_events_occurred_at", table_name="ai_usage_events")
