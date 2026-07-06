"""repair jobs constraints

Revision ID: core_0011
Revises: core_0010
Create Date: 2026-07-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0011"
down_revision: str | Sequence[str] | None = "core_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.drop_index("uq_jobs_in_flight", table_name="jobs", if_exists=True)
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
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'jobs_max_attempts_check'
                    AND conrelid = 'public.jobs'::regclass
                ) THEN
                    ALTER TABLE public.jobs
                    ADD CONSTRAINT jobs_max_attempts_check CHECK (max_attempts > 0);
                END IF;
            END $$;
            """
        )
    )


def downgrade() -> None:
    """Revert schema changes."""
