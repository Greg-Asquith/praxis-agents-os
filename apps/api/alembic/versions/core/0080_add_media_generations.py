# apps/api/alembic/versions/core/0080_add_media_generations.py

"""Adds the paid media generation record and generated revision provenance.

Revision ID: core_0080
Revises: core_0079
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "core_0080"
down_revision = "core_0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "file_revisions",
        sa.Column("generation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "media_generations",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_call_id", sa.String(length=128), nullable=False),
        sa.Column("task", sa.String(length=32), nullable=False),
        sa.Column("media_model", sa.String(length=64), nullable=False),
        sa.Column("route", sa.String(length=16), nullable=False),
        sa.Column("provider_model", sa.String(length=128), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'running', 'saved', 'failed')",
            name="ck_media_generations_status",
        ),
        sa.CheckConstraint(
            "status <> 'saved' OR revision_id IS NOT NULL",
            name="ck_media_generations_saved_revision",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revision_id"], ["file_revisions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "tool_call_id", name="uq_media_generations_run_tool_call"),
    )
    op.create_index(
        "ix_media_generations_workspace_created",
        "media_generations",
        ["workspace_id", "created_at"],
    )
    op.create_index("ix_media_generations_file_id", "media_generations", ["file_id"])
    op.create_index("ix_media_generations_revision_id", "media_generations", ["revision_id"])

    predicate = "workspace_id = current_setting('app.current_workspace_id', true)::uuid"
    op.execute(sa.text('ALTER TABLE "media_generations" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "media_generations" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            'CREATE POLICY "media_generations_tenant_isolation" ON "media_generations" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
    )
    op.execute(
        sa.text(
            'CREATE POLICY "maintenance_access" ON "media_generations" '
            "FOR ALL TO CURRENT_USER USING (true) WITH CHECK (true)"
        )
    )


def downgrade() -> None:
    op.drop_table("media_generations")
    op.drop_column("file_revisions", "generation")
