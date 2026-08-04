"""add event retention indexes

Revision ID: core_0034
Revises: core_0033
Create Date: 2026-08-04 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "core_0034"
down_revision: str | Sequence[str] | None = "core_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Support ordered, bounded audit and security event retention sweeps."""
    op.create_index(
        "ix_audit_events_retention",
        "audit_events",
        ["created_at", "id"],
    )
    op.create_index(
        "ix_security_events_retention",
        "security_events",
        ["created_at", "id"],
    )


def downgrade() -> None:
    """Remove event retention indexes."""
    op.drop_index("ix_security_events_retention", table_name="security_events")
    op.drop_index("ix_audit_events_retention", table_name="audit_events")
