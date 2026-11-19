# apps/api/alembic/versions/core/0083_add_mail_merge_test_sends.py

"""Adds the test emails people send themselves before approving a mail merge.

Revision ID: core_0083
Revises: core_0082
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "core_0083"
down_revision = "core_0082"
branch_labels = None
depends_on = None

_TABLE = "mail_merge_test_sends"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tool_call_id", sa.String(length=128), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["integration_connections.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mail_merge_test_sends_connection_attempted",
        _TABLE,
        ["connection_id", "attempted_at"],
    )
    op.create_index("ix_mail_merge_test_sends_run_tool_call", _TABLE, ["run_id", "tool_call_id"])

    predicate = "workspace_id = current_setting('app.current_workspace_id', true)::uuid"
    op.execute(sa.text(f'ALTER TABLE "{_TABLE}" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'ALTER TABLE "{_TABLE}" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            f'CREATE POLICY "{_TABLE}_tenant_isolation" ON "{_TABLE}" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
    )
    op.execute(
        sa.text(
            f'CREATE POLICY "maintenance_access" ON "{_TABLE}" '
            "FOR ALL TO CURRENT_USER USING (true) WITH CHECK (true)"
        )
    )


def downgrade() -> None:
    op.drop_table(_TABLE)
