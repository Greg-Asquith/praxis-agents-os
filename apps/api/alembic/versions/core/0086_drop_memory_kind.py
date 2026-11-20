# apps/api/alembic/versions/core/0086_drop_memory_kind.py

"""Drops the memory kind: every memory is recalled by relevance, none by a core list.

Revision ID: core_0086
Revises: core_0085
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0086"
down_revision = "core_0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_agent_memories_active_core_scope", table_name="agent_memories")
    op.drop_constraint("agent_memories_kind_check", "agent_memories", type_="check")
    op.drop_column("agent_memories", "kind")


def downgrade() -> None:
    op.add_column(
        "agent_memories",
        sa.Column("kind", sa.String(8), nullable=False, server_default=sa.text("'note'")),
    )
    op.create_check_constraint(
        "agent_memories_kind_check", "agent_memories", "kind IN ('core','note')"
    )
    op.create_index(
        "ix_agent_memories_active_core_scope",
        "agent_memories",
        ["workspace_id", "scope", "agent_id", "user_id"],
        postgresql_where=sa.text("status = 'active' AND kind = 'core'"),
    )
