"""Caches a revision's Gemini Files API upload.

Revision ID: core_0067
Revises: core_0066
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0067"
down_revision = "core_0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Adds the cached upload; existing workspace row-level security covers it."""
    op.add_column("file_revisions", sa.Column("gemini_file_name", sa.String(128), nullable=True))
    op.add_column("file_revisions", sa.Column("gemini_file_uri", sa.String(512), nullable=True))
    op.add_column(
        "file_revisions",
        sa.Column("gemini_file_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "file_revisions_gemini_file_check",
        "file_revisions",
        "(gemini_file_name IS NULL) = (gemini_file_uri IS NULL) AND "
        "(gemini_file_name IS NULL) = (gemini_file_expires_at IS NULL)",
    )


def downgrade() -> None:
    """Removes the cached upload."""
    op.drop_constraint("file_revisions_gemini_file_check", "file_revisions", type_="check")
    op.drop_column("file_revisions", "gemini_file_expires_at")
    op.drop_column("file_revisions", "gemini_file_uri")
    op.drop_column("file_revisions", "gemini_file_name")
