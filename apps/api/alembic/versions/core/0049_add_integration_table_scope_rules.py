"""Add integration table row-scope rules.

Revision ID: core_0049
Revises: core_0048
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "core_0049"
down_revision: str | Sequence[str] | None = "core_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Creates the rule table and its workspace-derived RLS policy."""
    op.create_table(
        "integration_table_scope_rules",
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("table_external_id", sa.String(length=1024), nullable=False),
        sa.Column("column_name", sa.String(length=300), nullable=False),
        sa.Column("column_type", sa.String(length=16), nullable=False),
        sa.Column(
            "allowed_values",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
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
            "jsonb_typeof(allowed_values) = 'array' AND jsonb_array_length(allowed_values) > 0",
            name="ck_integration_table_scope_rules_allowed_values_nonempty",
        ),
        sa.CheckConstraint(
            "char_length(btrim(column_name)) > 0",
            name="ck_integration_table_scope_rules_column_not_blank",
        ),
        sa.CheckConstraint(
            "column_type IN ('string', 'integer')",
            name="ck_integration_table_scope_rules_column_type",
        ),
        sa.CheckConstraint(
            "char_length(btrim(table_external_id)) > 0",
            name="ck_integration_table_scope_rules_table_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["integration_connections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by"],
            ["users.id"],
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
            name="uq_integration_table_scope_rules_resource_table",
        ),
    )
    op.create_index(
        "ix_integration_table_scope_rules_connection_id",
        "integration_table_scope_rules",
        ["connection_id"],
    )
    op.create_index(
        "ix_integration_table_scope_rules_resource_id",
        "integration_table_scope_rules",
        ["resource_id"],
    )
    op.create_index(
        "ix_integration_table_scope_rules_deleted_at",
        "integration_table_scope_rules",
        ["deleted_at"],
    )

    predicate = """
        EXISTS (
            SELECT 1
            FROM integration_resources AS resource
            JOIN integration_connections AS connection
              ON connection.id = resource.connection_id
            WHERE resource.id = integration_table_scope_rules.resource_id
              AND connection.id = integration_table_scope_rules.connection_id
              AND (
                  connection.owner_workspace_id =
                      current_setting('app.current_workspace_id', true)::uuid
                  OR connection.owner_user_id =
                      current_setting('app.current_user_id', true)::uuid
              )
        )
    """
    op.execute(sa.text('ALTER TABLE "integration_table_scope_rules" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "integration_table_scope_rules" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            'CREATE POLICY "integration_table_scope_rules_tenant_isolation" '
            'ON "integration_table_scope_rules" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
    )


def downgrade() -> None:
    """Removes integration table row-scope rules."""
    op.drop_index(
        "ix_integration_table_scope_rules_deleted_at",
        table_name="integration_table_scope_rules",
    )
    op.drop_index(
        "ix_integration_table_scope_rules_resource_id",
        table_name="integration_table_scope_rules",
    )
    op.drop_index(
        "ix_integration_table_scope_rules_connection_id",
        table_name="integration_table_scope_rules",
    )
    op.drop_table("integration_table_scope_rules")
