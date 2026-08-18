"""Add workspace classifier definitions.

Revision ID: core_0046
Revises: core_0045
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "core_0046"
down_revision = "core_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classifiers",
        sa.Column("name", sa.String(length=48), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_provider", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "(model_provider IS NULL) = (model IS NULL)",
            name="ck_classifiers_model_pair",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_classifiers_workspace_name"),
    )
    op.create_index("ix_classifiers_created_by", "classifiers", ["created_by"])
    op.create_index("ix_classifiers_deleted_at", "classifiers", ["deleted_at"])
    op.create_index(
        "ix_classifiers_workspace_active",
        "classifiers",
        ["workspace_id"],
        postgresql_where=sa.text("is_active = true AND deleted = false"),
    )
    op.create_index(
        "ix_classifiers_workspace_updated",
        "classifiers",
        ["workspace_id", "updated_at"],
    )

    predicate = "workspace_id = current_setting('app.current_workspace_id', true)::uuid"
    op.execute(sa.text('ALTER TABLE "classifiers" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "classifiers" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            'CREATE POLICY "classifiers_tenant_isolation" ON "classifiers" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
    )
    op.execute(
        sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE classifiers TO praxis_app")
    )


def downgrade() -> None:
    op.execute(sa.text('DROP POLICY IF EXISTS "classifiers_tenant_isolation" ON "classifiers"'))
    op.drop_table("classifiers")

