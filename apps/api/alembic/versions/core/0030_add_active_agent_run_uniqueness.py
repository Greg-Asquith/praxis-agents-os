"""enforce one active agent run per conversation

Revision ID: core_0030
Revises: core_0029
Create Date: 2026-07-30 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0030"
down_revision: str | Sequence[str] | None = "core_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_index(
        "uq_agent_runs_active_conversation",
        "agent_runs",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text(
            "deleted = false AND status IN ('pending', 'running', 'awaiting_approval')"
        ),
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index(
        "uq_agent_runs_active_conversation",
        table_name="agent_runs",
    )
