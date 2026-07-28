# apps/api/alembic/versions/core/0024_add_artifact_revisions.py

"""move artifacts to dedicated revisions

Revision ID: core_0024
Revises: core_0023
Create Date: 2026-07-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0024"
down_revision: str | Sequence[str] | None = "core_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing_artifact_count = op.get_bind().scalar(sa.text("SELECT count(*) FROM artifacts"))
    if existing_artifact_count:
        raise RuntimeError(
            "Cannot detach file-backed artifacts automatically; migrate their stored objects "
            "into the artifact namespace before applying core_0024"
        )

    op.create_table(
        "artifact_revisions",
        sa.Column("artifact_id", sa.UUID(), nullable=False),
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
        sa.Column(
            "created_by_system",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("restored_from_revision_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="artifact_revisions_revision_number_check",
        ),
        sa.CheckConstraint(
            "revision_kind IN ('create','edit','restore')",
            name="artifact_revisions_revision_kind_check",
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name="artifact_revisions_size_bytes_check",
        ),
        sa.CheckConstraint(
            "(CASE WHEN created_by_user_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN created_by_agent_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN created_by_system THEN 1 ELSE 0 END) = 1",
            name="artifact_revisions_exactly_one_actor_check",
        ),
        sa.CheckConstraint(
            "(revision_kind = 'restore') = (restored_from_revision_id IS NOT NULL)",
            name="artifact_revisions_restore_source_check",
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["restored_from_revision_id"],
            ["artifact_revisions.id"],
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_id",
            "revision_number",
            name="uq_artifact_revisions_artifact_number",
        ),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index(
        "ix_artifact_revisions_artifact_id",
        "artifact_revisions",
        ["artifact_id"],
    )
    op.create_index(
        "ix_artifact_revisions_workspace_id",
        "artifact_revisions",
        ["workspace_id"],
    )

    op.drop_constraint("artifacts_current_version_id_fkey", "artifacts", type_="foreignkey")
    op.drop_constraint("artifacts_file_id_fkey", "artifacts", type_="foreignkey")
    op.drop_constraint("artifacts_file_id_key", "artifacts", type_="unique")
    op.alter_column(
        "artifacts",
        "current_version_id",
        existing_type=sa.UUID(),
        nullable=True,
        comment="Nullable only while inserting the initial revision.",
    )
    op.drop_column("artifacts", "file_id")
    op.create_foreign_key(
        "fk_artifacts_current_version",
        "artifacts",
        "artifact_revisions",
        ["current_version_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_artifacts_current_version", "artifacts", type_="foreignkey")
    op.add_column("artifacts", sa.Column("file_id", sa.UUID(), nullable=True))
    op.execute(
        """
        UPDATE artifacts
        SET file_id = file_revisions.file_id
        FROM file_revisions
        WHERE file_revisions.id = artifacts.current_version_id
        """
    )
    missing_file_count = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM artifacts WHERE file_id IS NULL")
    )
    if missing_file_count:
        raise RuntimeError(
            "Cannot downgrade dedicated artifacts that have no file-backed revision history"
        )
    op.alter_column("artifacts", "file_id", existing_type=sa.UUID(), nullable=False)
    op.alter_column(
        "artifacts",
        "current_version_id",
        existing_type=sa.UUID(),
        nullable=False,
        comment=None,
    )
    op.create_unique_constraint("artifacts_file_id_key", "artifacts", ["file_id"])
    op.create_foreign_key(
        "artifacts_file_id_fkey",
        "artifacts",
        "files",
        ["file_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "artifacts_current_version_id_fkey",
        "artifacts",
        "file_revisions",
        ["current_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_index("ix_artifact_revisions_workspace_id", table_name="artifact_revisions")
    op.drop_index("ix_artifact_revisions_artifact_id", table_name="artifact_revisions")
    op.drop_table("artifact_revisions")
