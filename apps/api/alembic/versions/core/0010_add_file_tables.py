"""add file tables

Revision ID: core_0010
Revises: core_0009
Create Date: 2026-07-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0010"
down_revision: str | Sequence[str] | None = "core_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        "files",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("extension", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("content_hash", sa.String(length=64), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "current_revision_id",
            sa.UUID(),
            nullable=True,
            comment="Nullable only while inserting the initial revision.",
        ),
        sa.Column("revision_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "processing_status",
            sa.String(length=16),
            server_default=sa.text("'ready'"),
            nullable=False,
        ),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column(
            "processing_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "processing_attempts >= 0",
            name="files_processing_attempts_check",
        ),
        sa.CheckConstraint(
            "processing_status IN ('pending', 'processing', 'ready', 'error')",
            name="files_processing_status_check",
        ),
        sa.CheckConstraint("revision_count >= 0", name="files_revision_count_check"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_files_deleted_at", "files", ["deleted_at"], unique=False)
    op.create_index("ix_files_workspace_id", "files", ["workspace_id"], unique=False)
    op.create_index(
        "ix_files_workspace_created",
        "files",
        ["workspace_id", "created_at"],
        unique=False,
        postgresql_where=sa.text("deleted = false"),
    )
    op.create_index(
        "ix_files_workspace_processing",
        "files",
        ["workspace_id", "processing_status"],
        unique=False,
        postgresql_where=sa.text("deleted = false"),
    )

    op.create_table(
        "file_revisions",
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("revision_kind", sa.String(length=16), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("extension", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_by_agent_id", sa.UUID(), nullable=True),
        sa.Column("created_by_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("restored_from_revision_id", sa.UUID(), nullable=True),
        sa.Column("markdown_object_key", sa.String(length=1024), nullable=True),
        sa.Column("markdown_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(CASE WHEN created_by_user_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN created_by_agent_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN created_by_system THEN 1 ELSE 0 END) = 1",
            name="file_revisions_exactly_one_actor_check",
        ),
        sa.CheckConstraint(
            "revision_kind IN ('create', 'edit', 'replace', 'restore', 'import')",
            name="file_revisions_revision_kind_check",
        ),
        sa.CheckConstraint("revision_number > 0", name="file_revisions_revision_number_check"),
        sa.CheckConstraint(
            "(revision_kind = 'restore') = (restored_from_revision_id IS NOT NULL)",
            name="file_revisions_restore_source_check",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="file_revisions_size_bytes_check"),
        sa.ForeignKeyConstraint(["created_by_agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["restored_from_revision_id"], ["file_revisions.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id", "revision_number", name="uq_file_revisions_file_number"),
    )
    op.create_index("ix_file_revisions_file_id", "file_revisions", ["file_id"], unique=False)
    op.create_index(
        "ix_file_revisions_workspace_hash",
        "file_revisions",
        ["workspace_id", "content_hash"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_files_current_revision",
        "files",
        "file_revisions",
        ["current_revision_id"],
        ["id"],
    )

    op.create_table(
        "file_references",
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("file_revision_id", sa.UUID(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "target_type IN ('conversation', 'artifact', 'agent', 'schedule_run')",
            name="file_references_target_type_check",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_revision_id"], ["file_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "file_id",
            "target_type",
            "target_id",
            name="uq_file_references_file_target",
        ),
    )
    op.create_index("ix_file_references_workspace_id", "file_references", ["workspace_id"], unique=False)
    op.create_index(
        "ix_file_references_target",
        "file_references",
        ["target_type", "target_id"],
        unique=False,
    )

    op.create_table(
        "file_uploads",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column(
            "file_id",
            sa.UUID(),
            nullable=False,
            comment="No FK: new-file uploads are confirmed before the files row exists.",
        ),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("declared_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("declared_content_hash", sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_file_uploads_object_key"),
    )
    op.create_index("ix_file_uploads_workspace_id", "file_uploads", ["workspace_id"], unique=False)
    op.create_index(
        "ix_file_uploads_pending_expiry",
        "file_uploads",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("consumed_at IS NULL"),
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index("ix_file_uploads_pending_expiry", table_name="file_uploads")
    op.drop_index("ix_file_uploads_workspace_id", table_name="file_uploads")
    op.drop_table("file_uploads")
    op.drop_index("ix_file_references_target", table_name="file_references")
    op.drop_index("ix_file_references_workspace_id", table_name="file_references")
    op.drop_table("file_references")
    op.drop_constraint("fk_files_current_revision", "files", type_="foreignkey")
    op.drop_index("ix_file_revisions_workspace_hash", table_name="file_revisions")
    op.drop_index("ix_file_revisions_file_id", table_name="file_revisions")
    op.drop_table("file_revisions")
    op.drop_index("ix_files_workspace_processing", table_name="files")
    op.drop_index("ix_files_workspace_created", table_name="files")
    op.drop_index("ix_files_workspace_id", table_name="files")
    op.drop_index("ix_files_deleted_at", table_name="files")
    op.drop_table("files")
