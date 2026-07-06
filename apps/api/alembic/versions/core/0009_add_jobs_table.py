"""add jobs table

Revision ID: core_0009
Revises: core_0008
Create Date: 2026-07-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "core_0009"
down_revision: str | Sequence[str] | None = "core_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        "jobs",
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=64), nullable=True),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("initiated_by_user_id", sa.UUID(), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("attempts >= 0", name="jobs_attempts_check"),
        sa.CheckConstraint("max_attempts > 0", name="jobs_max_attempts_check"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="jobs_status_check",
        ),
        sa.ForeignKeyConstraint(["initiated_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_initiated_by_user_id", "jobs", ["initiated_by_user_id"], unique=False)
    op.create_index(
        "ix_jobs_claim",
        "jobs",
        ["status", "run_after", "priority"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_jobs_reclaim",
        "jobs",
        ["status", "lock_expires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index("ix_jobs_workspace_id", "jobs", ["workspace_id"], unique=False)
    op.create_index("ix_jobs_workspace_status", "jobs", ["workspace_id", "status"], unique=False)
    op.create_index(
        "uq_jobs_in_flight",
        "jobs",
        [
            sa.text("coalesce(workspace_id::text, '')"),
            sa.text("kind"),
            sa.text("coalesce(subject_type, '')"),
            sa.text("coalesce(subject_id::text, '')"),
            sa.text("content_hash"),
        ],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index("uq_jobs_in_flight", table_name="jobs")
    op.drop_index("ix_jobs_workspace_status", table_name="jobs")
    op.drop_index("ix_jobs_workspace_id", table_name="jobs")
    op.drop_index("ix_jobs_reclaim", table_name="jobs")
    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.drop_index("ix_jobs_initiated_by_user_id", table_name="jobs")
    op.drop_table("jobs")
