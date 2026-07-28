# apps/api/alembic/versions/core/0023_add_artifacts_table.py

"""add file-backed artifacts table

Revision ID: core_0023
Revises: core_0022
Create Date: 2026-07-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0023"
down_revision: str | Sequence[str] | None = "core_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("current_version_id", sa.UUID(), nullable=False),
        sa.Column("artifact_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "artifact_type IN ('html','markdown','mermaid','csv','image-ref')",
            name="artifacts_type_check",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id"),
    )
    op.create_index("ix_artifacts_workspace_id", "artifacts", ["workspace_id"])
    op.create_index("ix_artifacts_conversation_id", "artifacts", ["conversation_id"])
    op.create_index("ix_artifacts_deleted_at", "artifacts", ["deleted_at"])
    op.create_index(
        "ix_artifacts_workspace_created",
        "artifacts",
        ["workspace_id", "created_at"],
        postgresql_where=sa.text("deleted = false"),
    )
    op.create_foreign_key(
        "artifacts_current_version_id_fkey",
        "artifacts",
        "file_revisions",
        ["current_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("artifacts_current_version_id_fkey", "artifacts", type_="foreignkey")
    op.drop_index("ix_artifacts_workspace_created", table_name="artifacts")
    op.drop_index("ix_artifacts_deleted_at", table_name="artifacts")
    op.drop_index("ix_artifacts_conversation_id", table_name="artifacts")
    op.drop_index("ix_artifacts_workspace_id", table_name="artifacts")
    op.drop_table("artifacts")
