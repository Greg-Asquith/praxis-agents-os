# apps/api/alembic/versions/core/0082_add_mail_merges.py

"""Adds mail merges and their per-recipient send records.

Revision ID: core_0082
Revises: core_0081
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "core_0082"
down_revision = "core_0081"
branch_labels = None
depends_on = None

_TABLES = ("mail_merges", "mail_merge_recipients")


def upgrade() -> None:
    op.create_table(
        "mail_merges",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tool_call_id", sa.String(length=128), nullable=False),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("sender_address", sa.String(length=320), nullable=False),
        sa.Column("subject_template", sa.Text(), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column(
            "fallbacks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'sending', 'paused', 'completed', 'cancelled', 'stopped')",
            name="ck_mail_merges_status",
        ),
        sa.CheckConstraint(
            "provider_key IN ('gmail', 'outlook_mail')", name="ck_mail_merges_provider_key"
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["integration_connections.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "tool_call_id", name="uq_mail_merges_run_tool_call"),
    )
    op.create_index(
        "uq_mail_merges_active_connection",
        "mail_merges",
        ["connection_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'sending')"),
    )
    op.create_index(
        "ix_mail_merges_workspace_created", "mail_merges", ["workspace_id", "created_at"]
    )

    op.create_table(
        "mail_merge_recipients",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merge_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("message_id_header", sa.String(length=998), nullable=True),
        sa.Column("provider_message_id", sa.String(length=512), nullable=True),
        sa.Column("provider_draft_id", sa.String(length=512), nullable=True),
        sa.Column("provider_thread_id", sa.String(length=512), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'failed', 'unverified', 'skipped')",
            name="ck_mail_merge_recipients_status",
        ),
        sa.CheckConstraint(
            "email = lower(btrim(email)) AND length(email) >= 3",
            name="ck_mail_merge_recipients_email",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'skipped') OR attempted_at IS NOT NULL",
            name="ck_mail_merge_recipients_attempted",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["merge_id"], ["mail_merges.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merge_id", "email", name="uq_mail_merge_recipients_email"),
    )
    op.create_index(
        "ix_mail_merge_recipients_merge_status",
        "mail_merge_recipients",
        ["merge_id", "status", "position"],
    )
    op.create_index(
        "ix_mail_merge_recipients_workspace_attempted",
        "mail_merge_recipients",
        ["workspace_id", "attempted_at"],
    )

    predicate = "workspace_id = current_setting('app.current_workspace_id', true)::uuid"
    for table in _TABLES:
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
                f"USING ({predicate}) WITH CHECK ({predicate})"
            )
        )
        op.execute(
            sa.text(
                f'CREATE POLICY "maintenance_access" ON "{table}" '
                "FOR ALL TO CURRENT_USER USING (true) WITH CHECK (true)"
            )
        )


def downgrade() -> None:
    op.drop_table("mail_merge_recipients")
    op.drop_table("mail_merges")
