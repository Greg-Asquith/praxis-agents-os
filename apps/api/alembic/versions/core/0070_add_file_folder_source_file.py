"""Links a folder to the File its outputs come from.

Revision ID: core_0070
Revises: core_0069
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "core_0070"
down_revision = "core_0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Adds the link; existing workspace row-level security covers it."""
    op.add_column(
        "file_folders",
        sa.Column("source_file_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "file_folders_source_file_id_fkey",
        "file_folders",
        "files",
        ["source_file_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_file_folders_workspace_source_file_live",
        "file_folders",
        ["workspace_id", "source_file_id"],
        unique=True,
        postgresql_where=sa.text("deleted = false AND source_file_id IS NOT NULL"),
    )
    op.create_index("ix_file_folders_source_file", "file_folders", ["source_file_id"])


def downgrade() -> None:
    """Removes the link."""
    op.drop_index("ix_file_folders_source_file", table_name="file_folders")
    op.drop_index("uq_file_folders_workspace_source_file_live", table_name="file_folders")
    op.drop_constraint("file_folders_source_file_id_fkey", "file_folders", type_="foreignkey")
    op.drop_column("file_folders", "source_file_id")
