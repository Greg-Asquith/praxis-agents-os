"""add tool columns to audit events

Revision ID: core_0007
Revises: core_0006
Create Date: 2026-07-03 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0007"
down_revision: str | Sequence[str] | None = "core_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.add_column("audit_events", sa.Column("tool_name", sa.String(length=100), nullable=True))
    op.add_column(
        "audit_events",
        sa.Column("tool_provider", sa.String(length=50), nullable=True),
    )
    op.create_index("ix_audit_events_tool_name", "audit_events", ["tool_name"], unique=False)
    op.create_index(
        "ix_audit_events_workspace_tool_occurred",
        "audit_events",
        ["workspace_id", "tool_name", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index("ix_audit_events_workspace_tool_occurred", table_name="audit_events")
    op.drop_index("ix_audit_events_tool_name", table_name="audit_events")
    op.drop_column("audit_events", "tool_provider")
    op.drop_column("audit_events", "tool_name")
