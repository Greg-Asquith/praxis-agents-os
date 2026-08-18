"""Index file-folder foreign keys used by delete operations.

Revision ID: core_0045
Revises: core_0044
"""

from alembic import op

revision = "core_0045"
down_revision = "core_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_file_folders_source_conversation",
        "file_folders",
        ["source_conversation_id"],
    )
    op.create_index("ix_files_folder_id", "files", ["folder_id"])


def downgrade() -> None:
    op.drop_index("ix_files_folder_id", table_name="files")
    op.drop_index("ix_file_folders_source_conversation", table_name="file_folders")
