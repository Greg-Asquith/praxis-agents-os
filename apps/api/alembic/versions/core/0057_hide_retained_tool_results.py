"""Keeps retained tool results outside the document library.

Revision ID: core_0057
Revises: core_0056
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0057"
down_revision = "core_0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("is_tool_result", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        "files_tool_result_storage_check",
        "files",
        "NOT is_tool_result OR (scope = 'workspace' AND folder_id IS NULL)",
    )


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM files WHERE is_tool_result) THEN
                RAISE EXCEPTION 'Remove retained tool results before downgrading';
            END IF;
        END $$;
    """)
    op.drop_constraint("files_tool_result_storage_check", "files", type_="check")
    op.drop_column("files", "is_tool_result")
