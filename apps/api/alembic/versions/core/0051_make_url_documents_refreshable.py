"""Make URL Knowledge Base documents refreshable.

Revision ID: core_0051
Revises: core_0050
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0051"
down_revision: str | Sequence[str] | None = "core_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Adds synchronization metadata to URL Knowledge Base documents."""
    op.drop_constraint(
        "ck_kb_documents_integration_source",
        "kb_documents",
        type_="check",
    )
    op.execute(
        sa.text(
            "UPDATE kb_documents "
            "SET source_sync_status = CASE status "
            "WHEN 'ready' THEN 'ready' "
            "WHEN 'error' THEN 'error' "
            "ELSE 'pending' END, "
            "source_synced_at = CASE WHEN status = 'ready' THEN updated_at ELSE NULL END "
            "WHERE source_type = 'url'"
        )
    )
    op.create_check_constraint(
        "ck_kb_documents_refreshable_source",
        "kb_documents",
        "(source_type IN ('url', 'integration') "
        "AND source_sync_status IS NOT NULL) OR "
        "(source_type NOT IN ('url', 'integration') "
        "AND source_sync_status IS NULL AND source_synced_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_kb_documents_integration_binding",
        "kb_documents",
        "(source_type = 'integration' AND external_id IS NOT NULL) OR "
        "(source_type <> 'integration' AND integration_resource_id IS NULL)",
    )
    op.drop_index("ix_kb_documents_integration_scan", table_name="kb_documents")
    op.create_index(
        "ix_kb_documents_source_scan",
        "kb_documents",
        ["source_synced_at"],
        postgresql_where=sa.text(
            "source_type IN ('url', 'integration') AND deleted = false "
            "AND source_sync_status IN ('ready', 'error', 'unavailable')"
        ),
    )


def downgrade() -> None:
    """Restores integration-only synchronization metadata."""
    op.drop_constraint(
        "ck_kb_documents_integration_binding",
        "kb_documents",
        type_="check",
    )
    op.drop_constraint(
        "ck_kb_documents_refreshable_source",
        "kb_documents",
        type_="check",
    )
    op.drop_index("ix_kb_documents_source_scan", table_name="kb_documents")
    op.execute(
        sa.text(
            "UPDATE kb_documents "
            "SET source_sync_status = NULL, source_synced_at = NULL "
            "WHERE source_type = 'url'"
        )
    )
    op.create_check_constraint(
        "ck_kb_documents_integration_source",
        "kb_documents",
        "(source_type = 'integration' AND external_id IS NOT NULL "
        "AND source_sync_status IS NOT NULL) OR "
        "(source_type <> 'integration' AND integration_resource_id IS NULL "
        "AND source_sync_status IS NULL AND source_synced_at IS NULL)",
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
