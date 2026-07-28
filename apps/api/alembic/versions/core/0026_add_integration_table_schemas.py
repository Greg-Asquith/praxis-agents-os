"""add integration table schema cache

Revision ID: core_0026
Revises: core_0025
Create Date: 2026-07-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "core_0026"
down_revision: str | Sequence[str] | None = "core_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        "integration_table_schemas",
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("table_external_id", sa.String(length=1024), nullable=False),
        sa.Column("table_type", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "schema_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "partitioning",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "clustering_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("provider_last_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "availability",
            sa.String(length=16),
            server_default=sa.text("'available'"),
            nullable=False,
        ),
        sa.Column("first_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "availability IN ('available', 'removed')",
            name="ck_integration_table_schemas_availability",
        ),
        sa.CheckConstraint(
            "row_count IS NULL OR row_count >= 0",
            name="ck_integration_table_schemas_row_count_nonnegative",
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_integration_table_schemas_size_bytes_nonnegative",
        ),
        sa.CheckConstraint(
            "table_type IN ('table', 'view', 'materialized_view', 'external')",
            name="ck_integration_table_schemas_table_type",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["integration_resources.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resource_id",
            "table_external_id",
            name="uq_integration_table_schemas_resource_table",
        ),
    )
    op.create_index(
        "ix_integration_table_schemas_resource_id",
        "integration_table_schemas",
        ["resource_id"],
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index(
        "ix_integration_table_schemas_resource_id",
        table_name="integration_table_schemas",
    )
    op.drop_table("integration_table_schemas")
