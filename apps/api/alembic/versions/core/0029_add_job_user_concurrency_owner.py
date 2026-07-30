"""add job user concurrency owner

Revision ID: core_0029
Revises: core_0028
Create Date: 2026-07-30 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0029"
down_revision: str | Sequence[str] | None = "core_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.add_column("jobs", sa.Column("concurrency_user_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "jobs_concurrency_user_id_fkey",
        "jobs",
        "users",
        ["concurrency_user_id"],
        ["id"],
    )
    op.execute(
        sa.text(
            """
            UPDATE jobs AS job
            SET concurrency_user_id = connection.owner_user_id
            FROM integration_connections AS connection
            WHERE job.kind = 'integrations.discover_resources'
              AND job.subject_type = 'integration_connection'
              AND job.subject_id = connection.id
              AND job.workspace_id IS NULL
              AND connection.owner_user_id IS NOT NULL
            """
        )
    )
    op.create_check_constraint(
        "jobs_concurrency_owner_check",
        "jobs",
        "num_nonnulls(workspace_id, concurrency_user_id) <= 1",
    )
    op.create_index(
        "ix_jobs_concurrency_user_id",
        "jobs",
        ["concurrency_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_jobs_concurrency_user_status",
        "jobs",
        ["concurrency_user_id", "status"],
        unique=False,
    )
    op.drop_index("uq_jobs_in_flight", table_name="jobs")
    op.create_index(
        "uq_jobs_in_flight",
        "jobs",
        [
            sa.text("coalesce(workspace_id::text, '')"),
            sa.text("coalesce(concurrency_user_id::text, '')"),
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
    op.drop_index("ix_jobs_concurrency_user_status", table_name="jobs")
    op.drop_index("ix_jobs_concurrency_user_id", table_name="jobs")
    op.drop_constraint("jobs_concurrency_owner_check", "jobs", type_="check")
    op.drop_constraint("jobs_concurrency_user_id_fkey", "jobs", type_="foreignkey")
    op.drop_column("jobs", "concurrency_user_id")
