# apps/api/alembic/versions/core/0066_add_file_revision_media_metadata.py

"""Adds measured media metadata to file revisions.

Revision ID: core_0066
Revises: core_0065
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "core_0066"
down_revision = "core_0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Adds the set-once probe result; existing workspace row-level security covers it."""
    op.add_column(
        "file_revisions",
        sa.Column("media_metadata", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    """Removes the probe result."""
    op.drop_column("file_revisions", "media_metadata")
