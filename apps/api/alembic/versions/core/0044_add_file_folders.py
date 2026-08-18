"""Add workspace file folders.

Revision ID: core_0044
Revises: core_0043
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "core_0044"
down_revision = "core_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_folders",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "(CASE WHEN created_by_user_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN created_by_agent_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="file_folders_exactly_one_creator_check",
        ),
        sa.ForeignKeyConstraint(["created_by_agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_file_folders_deleted_at", "file_folders", ["deleted_at"])
    op.create_index(
        "uq_file_folders_workspace_name_live",
        "file_folders",
        ["workspace_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted = false"),
    )
    op.create_index(
        "uq_file_folders_workspace_conversation_live",
        "file_folders",
        ["workspace_id", "source_conversation_id"],
        unique=True,
        postgresql_where=sa.text("deleted = false AND source_conversation_id IS NOT NULL"),
    )
    op.add_column("files", sa.Column("folder_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_files_folder_id_file_folders",
        "files",
        "file_folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_files_workspace_folder",
        "files",
        ["workspace_id", "folder_id"],
        postgresql_where=sa.text("deleted = false"),
    )
    predicate = "workspace_id = current_setting('app.current_workspace_id', true)::uuid"
    op.execute(sa.text('ALTER TABLE "file_folders" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "file_folders" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            'CREATE POLICY "file_folders_tenant_isolation" ON "file_folders" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_files_workspace_folder", table_name="files")
    op.drop_constraint("fk_files_folder_id_file_folders", "files", type_="foreignkey")
    op.drop_column("files", "folder_id")
    op.drop_index("uq_file_folders_workspace_conversation_live", table_name="file_folders")
    op.drop_index("uq_file_folders_workspace_name_live", table_name="file_folders")
    op.drop_index("ix_file_folders_deleted_at", table_name="file_folders")
    op.drop_table("file_folders")
