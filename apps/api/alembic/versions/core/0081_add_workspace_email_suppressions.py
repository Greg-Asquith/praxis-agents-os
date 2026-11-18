# apps/api/alembic/versions/core/0081_add_workspace_email_suppressions.py

"""Adds the workspace Do Not Email list.

Revision ID: core_0081
Revises: core_0080
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "core_0081"
down_revision = "core_0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_email_suppressions",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("match_key", sa.String(length=320), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=16), server_default=sa.text("'manual'"), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "email = lower(btrim(email)) AND length(email) >= 3",
            name="ck_workspace_email_suppressions_email",
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) >= 1", name="ck_workspace_email_suppressions_reason"
        ),
        sa.CheckConstraint("source IN ('manual')", name="ck_workspace_email_suppressions_source"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "match_key", name="uq_workspace_email_suppressions_match_key"
        ),
    )
    op.create_index(
        "ix_workspace_email_suppressions_workspace_created",
        "workspace_email_suppressions",
        ["workspace_id", "created_at"],
    )

    predicate = "workspace_id = current_setting('app.current_workspace_id', true)::uuid"
    op.execute(sa.text('ALTER TABLE "workspace_email_suppressions" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "workspace_email_suppressions" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            'CREATE POLICY "workspace_email_suppressions_tenant_isolation" '
            'ON "workspace_email_suppressions" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
    )
    op.execute(
        sa.text(
            'CREATE POLICY "maintenance_access" ON "workspace_email_suppressions" '
            "FOR ALL TO CURRENT_USER USING (true) WITH CHECK (true)"
        )
    )


def downgrade() -> None:
    op.drop_table("workspace_email_suppressions")
