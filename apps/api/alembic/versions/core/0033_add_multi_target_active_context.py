"""add multi-target active context

Revision ID: core_0033
Revises: core_0032
Create Date: 2026-08-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0033"
down_revision: str | Sequence[str] | None = "core_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow each conversation to select a set of distinct context targets."""
    op.drop_constraint(
        "uq_active_context_selections_conversation",
        "active_context_selections",
        type_="unique",
    )
    op.create_index(
        "ix_active_context_selections_conversation_id",
        "active_context_selections",
        ["conversation_id"],
    )
    op.create_index(
        "uq_active_context_selections_conversation_resource",
        "active_context_selections",
        ["conversation_id", "integration_resource_id"],
        unique=True,
        postgresql_where=sa.text("integration_resource_id IS NOT NULL"),
    )
    op.create_index(
        "uq_active_context_selections_conversation_group",
        "active_context_selections",
        ["conversation_id", "context_group_id"],
        unique=True,
        postgresql_where=sa.text("context_group_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Restore the single-target conversation constraint."""
    op.drop_index(
        "uq_active_context_selections_conversation_group",
        table_name="active_context_selections",
        postgresql_where=sa.text("context_group_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_active_context_selections_conversation_resource",
        table_name="active_context_selections",
        postgresql_where=sa.text("integration_resource_id IS NOT NULL"),
    )
    op.drop_index(
        "ix_active_context_selections_conversation_id",
        table_name="active_context_selections",
    )
    op.create_unique_constraint(
        "uq_active_context_selections_conversation",
        "active_context_selections",
        ["conversation_id"],
    )
