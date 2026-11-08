# apps/api/alembic/versions/core/0078_pending_job_dedupe_and_kb_source_version.py

"""Dedupes only pending jobs and versions knowledge document sources.

Revision ID: core_0078
Revises: core_0077
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "core_0078"
down_revision = "core_0077"
branch_labels = None
depends_on = None

_DEDUPE_COLUMNS = [
    sa.text("coalesce(workspace_id::text, '')"),
    sa.text("coalesce(concurrency_user_id::text, '')"),
    sa.text("kind"),
    sa.text("coalesce(subject_type, '')"),
    sa.text("coalesce(subject_id::text, '')"),
    sa.text("content_hash"),
]


def upgrade() -> None:
    """Lets a re-enqueue during a running job queue one follow-up."""
    op.drop_index("uq_jobs_in_flight", table_name="jobs")
    op.create_index(
        "uq_jobs_pending",
        "jobs",
        _DEDUPE_COLUMNS,
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.add_column(
        "kb_documents",
        sa.Column(
            "source_version",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )


def downgrade() -> None:
    """Restores in-flight dedupe; fails while a pending follow-up shares a running job's key."""
    op.drop_column("kb_documents", "source_version")
    op.drop_index("uq_jobs_pending", table_name="jobs")
    op.create_index(
        "uq_jobs_in_flight",
        "jobs",
        _DEDUPE_COLUMNS,
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
