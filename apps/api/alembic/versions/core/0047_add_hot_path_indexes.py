"""Add indexes for recurring worker queries and foreign keys.

Revision ID: core_0047
Revises: core_0046
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0047"
down_revision: str | Sequence[str] | None = "core_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PENDING_JOBS = sa.text("status = 'pending'")
_DUE_SCHEDULES = sa.text("deleted = false AND is_active = true")

_INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    ("ix_ai_usage_events_agent_id", "ai_usage_events", ["agent_id"]),
    ("ix_ai_usage_events_conversation_id", "ai_usage_events", ["conversation_id"]),
    ("ix_ai_usage_events_run_id", "ai_usage_events", ["run_id"]),
    ("ix_ai_usage_events_user_id", "ai_usage_events", ["user_id"]),
    ("ix_artifacts_current_version_id", "artifacts", ["current_version_id"]),
    ("ix_artifacts_agent_id", "artifacts", ["agent_id"]),
    ("ix_artifacts_run_id", "artifacts", ["run_id"]),
    (
        "ix_artifact_revisions_created_by_user_id",
        "artifact_revisions",
        ["created_by_user_id"],
    ),
    (
        "ix_artifact_revisions_created_by_agent_id",
        "artifact_revisions",
        ["created_by_agent_id"],
    ),
    (
        "ix_artifact_revisions_restored_from_revision_id",
        "artifact_revisions",
        ["restored_from_revision_id"],
    ),
    ("ix_file_revisions_created_by_user_id", "file_revisions", ["created_by_user_id"]),
    (
        "ix_file_revisions_created_by_agent_id",
        "file_revisions",
        ["created_by_agent_id"],
    ),
    (
        "ix_file_revisions_restored_from_revision_id",
        "file_revisions",
        ["restored_from_revision_id"],
    ),
    (
        "ix_agent_memories_source_conversation_id",
        "agent_memories",
        ["source_conversation_id"],
    ),
    ("ix_agent_memories_source_run_id", "agent_memories", ["source_run_id"]),
    ("ix_agent_memories_workspace_agent", "agent_memories", ["workspace_id", "agent_id"]),
)


def upgrade() -> None:
    """Creates hot-path indexes without blocking writes to populated tables."""
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_agent_schedules_due",
            "agent_schedules",
            ["next_run_at"],
            postgresql_concurrently=True,
            postgresql_where=_DUE_SCHEDULES,
        )
        op.drop_index(
            "ix_jobs_claim",
            table_name="jobs",
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_jobs_claim",
            "jobs",
            ["priority", "run_after", "created_at"],
            postgresql_concurrently=True,
            postgresql_where=_PENDING_JOBS,
        )
        for name, table_name, columns in _INDEXES:
            op.create_index(
                name,
                table_name,
                columns,
                postgresql_concurrently=True,
            )


def downgrade() -> None:
    """Restores the earlier job-claim index and removes the added indexes."""
    with op.get_context().autocommit_block():
        for name, table_name, _columns in reversed(_INDEXES):
            op.drop_index(
                name,
                table_name=table_name,
                postgresql_concurrently=True,
            )
        op.drop_index(
            "ix_jobs_claim",
            table_name="jobs",
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_jobs_claim",
            "jobs",
            ["status", "run_after", "priority"],
            postgresql_concurrently=True,
            postgresql_where=_PENDING_JOBS,
        )
        op.drop_index(
            "ix_agent_schedules_due",
            table_name="agent_schedules",
            postgresql_concurrently=True,
        )
