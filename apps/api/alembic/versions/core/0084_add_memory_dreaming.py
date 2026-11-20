# apps/api/alembic/versions/core/0084_add_memory_dreaming.py

"""Adds dream runs, dream memory provenance, user-edit tracking, and dream usage.

Revision ID: core_0084
Revises: core_0083
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "core_0084"
down_revision = "core_0083"
branch_labels = None
depends_on = None

_SOURCES_BEFORE = ("interactive", "scheduled", "delegated", "event", "user")
_CREATED_BY_BEFORE = ("agent", "user")
_ARCHIVE_REASONS_BEFORE = ("expired", "forgotten", "user_deleted")
_PURPOSES_BEFORE = (
    "agent_run",
    "conversation_naming",
    "history_summary",
    "run_review",
    "kb_annotation",
    "classification",
    "web_search",
    "web_fetch",
    "image_generation",
    "code_execution",
    "video_understanding",
    "video_generation",
    "video_transcription",
    "embedding_kb_ingest",
    "embedding_kb_search",
    "embedding_memory_write",
    "embedding_memory_search",
    "embedding_memory_dedup",
)
_PURPOSES_AFTER = (*_PURPOSES_BEFORE[:4], "memory_dreaming", *_PURPOSES_BEFORE[4:])


def _values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, condition)


def _replace_memory_checks(
    *, sources: tuple[str, ...], created_by: tuple[str, ...], reasons: tuple[str, ...]
) -> None:
    _replace_check(
        "agent_memories", "agent_memories_source_check", f"source IN ({_values(sources)})"
    )
    _replace_check(
        "agent_memories",
        "agent_memories_created_by_check",
        f"created_by IN ({_values(created_by)})",
    )
    _replace_check(
        "agent_memories",
        "agent_memories_archive_reason_check",
        f"archive_reason IS NULL OR archive_reason IN ({_values(reasons)})",
    )


def upgrade() -> None:
    _replace_memory_checks(
        sources=(*_SOURCES_BEFORE, "dream"),
        created_by=(*_CREATED_BY_BEFORE, "system"),
        reasons=(*_ARCHIVE_REASONS_BEFORE, "consolidated"),
    )
    op.add_column(
        "agent_memories",
        sa.Column("last_edited_by_user_at", sa.DateTime(timezone=True), nullable=True),
    )
    _replace_check(
        "ai_usage_events",
        "ai_usage_events_purpose_check",
        f"purpose IN ({_values(_PURPOSES_AFTER)})",
    )

    op.create_table(
        "memory_dream_runs",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'collecting'"), nullable=False
        ),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "conversations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "batch_handles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "applied_scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "operation_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "usage_totals",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('collecting', 'extracting', 'consolidating', 'applying', "
            "'completed', 'failed')",
            name="ck_memory_dream_runs_status",
        ),
        sa.CheckConstraint(
            "(status IN ('completed', 'failed')) = (finished_at IS NOT NULL)",
            name="ck_memory_dream_runs_finished",
        ),
        sa.CheckConstraint(
            "window_start IS NULL OR window_start <= window_end",
            name="ck_memory_dream_runs_window",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_memory_dream_runs_active_workspace",
        "memory_dream_runs",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('completed', 'failed')"),
    )
    op.create_index(
        "ix_memory_dream_runs_workspace_window",
        "memory_dream_runs",
        ["workspace_id", "window_end"],
        postgresql_where=sa.text("status = 'completed'"),
    )

    predicate = "workspace_id = current_setting('app.current_workspace_id', true)::uuid"
    op.execute(sa.text('ALTER TABLE "memory_dream_runs" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "memory_dream_runs" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            'CREATE POLICY "memory_dream_runs_tenant_isolation" ON "memory_dream_runs" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
    )
    op.execute(
        sa.text(
            'CREATE POLICY "maintenance_access" ON "memory_dream_runs" '
            "FOR ALL TO CURRENT_USER USING (true) WITH CHECK (true)"
        )
    )


def downgrade() -> None:
    op.drop_table("memory_dream_runs")
    op.execute("DELETE FROM ai_usage_events WHERE purpose = 'memory_dreaming'")
    _replace_check(
        "ai_usage_events",
        "ai_usage_events_purpose_check",
        f"purpose IN ({_values(_PURPOSES_BEFORE)})",
    )
    op.drop_column("agent_memories", "last_edited_by_user_at")
    # Undo dream changes so the older checks hold: restore what a dream replaced or retired.
    op.execute(
        "UPDATE agent_memories SET status = 'active', superseded_by_id = NULL "
        "WHERE superseded_by_id IN (SELECT id FROM agent_memories WHERE created_by = 'system')"
    )
    op.execute(
        "UPDATE agent_memories SET status = 'active', archived_at = NULL, archive_reason = NULL "
        "WHERE archive_reason = 'consolidated'"
    )
    op.execute("DELETE FROM agent_memories WHERE source = 'dream' OR created_by = 'system'")
    _replace_memory_checks(
        sources=_SOURCES_BEFORE,
        created_by=_CREATED_BY_BEFORE,
        reasons=_ARCHIVE_REASONS_BEFORE,
    )
