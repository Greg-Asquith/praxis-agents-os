# apps/api/alembic/versions/core/0069_add_file_revision_video_analysis.py

"""Stores a video revision's transcript and shot cuts.

Revision ID: core_0069
Revises: core_0068
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "core_0069"
down_revision = "core_0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Adds the derived analysis; existing workspace row-level security covers it."""
    op.add_column(
        "file_revisions", sa.Column("transcript_object_key", sa.String(1024), nullable=True)
    )
    op.add_column(
        "file_revisions", sa.Column("transcript_size_bytes", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "file_revisions",
        sa.Column("shot_cuts_ms", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        "file_revisions_transcript_check",
        "file_revisions",
        "(transcript_object_key IS NULL) = (transcript_size_bytes IS NULL)",
    )


def downgrade() -> None:
    """Removes the derived analysis."""
    op.drop_constraint("file_revisions_transcript_check", "file_revisions", type_="check")
    op.drop_column("file_revisions", "shot_cuts_ms")
    op.drop_column("file_revisions", "transcript_size_bytes")
    op.drop_column("file_revisions", "transcript_object_key")
