"""Add Knowledge Base integration source bindings.

Revision ID: core_0050
Revises: core_0049
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0050"
down_revision: str | Sequence[str] | None = "core_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Adds provider-neutral source binding and synchronization metadata."""
    op.add_column(
        "kb_documents",
        sa.Column("integration_resource_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "kb_documents",
        sa.Column("source_sync_status", sa.String(length=24), nullable=True),
    )
    op.add_column(
        "kb_documents",
        sa.Column("source_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_kb_documents_integration_resource",
        "kb_documents",
        ["integration_resource_id"],
    )
    op.create_index(
        "ix_kb_documents_integration_scan",
        "kb_documents",
        ["source_synced_at"],
        postgresql_where=sa.text(
            "source_type = 'integration' AND deleted = false "
            "AND source_sync_status IN ('ready', 'error', 'unavailable')"
        ),
    )
    op.create_index(
        "ix_kb_documents_integration_source",
        "kb_documents",
        ["integration_resource_id", "external_id"],
        postgresql_where=sa.text("source_type = 'integration' AND deleted = false"),
    )
    op.create_foreign_key(
        "fk_kb_documents_integration_resource_id",
        "kb_documents",
        "integration_resources",
        ["integration_resource_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_kb_documents_integration_source",
        "kb_documents",
        "(source_type = 'integration' AND external_id IS NOT NULL "
        "AND source_sync_status IS NOT NULL) OR "
        "(source_type <> 'integration' AND integration_resource_id IS NULL "
        "AND source_sync_status IS NULL AND source_synced_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_kb_documents_source_sync_status",
        "kb_documents",
        "source_sync_status IN ('pending','ready','unavailable','disconnected','error')",
    )


def downgrade() -> None:
    """Removes provider-neutral source binding and synchronization metadata."""
    op.drop_constraint(
        "ck_kb_documents_source_sync_status",
        "kb_documents",
        type_="check",
    )
    op.drop_constraint(
        "ck_kb_documents_integration_source",
        "kb_documents",
        type_="check",
    )
    op.drop_constraint(
        "fk_kb_documents_integration_resource_id",
        "kb_documents",
        type_="foreignkey",
    )
    op.drop_index("ix_kb_documents_integration_source", table_name="kb_documents")
    op.drop_index("ix_kb_documents_integration_scan", table_name="kb_documents")
    op.drop_index("ix_kb_documents_integration_resource", table_name="kb_documents")
    op.drop_column("kb_documents", "source_synced_at")
    op.drop_column("kb_documents", "source_sync_status")
    op.drop_column("kb_documents", "integration_resource_id")
