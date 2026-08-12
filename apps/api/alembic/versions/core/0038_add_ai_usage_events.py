"""add ai usage events

Revision ID: core_0038
Revises: core_0037
Create Date: 2026-08-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "core_0038"
down_revision: str | Sequence[str] | None = "core_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PURPOSES = (
    "agent_run",
    "conversation_naming",
    "history_summary",
    "kb_annotation",
    "web_search",
    "web_fetch",
    "image_generation",
    "embedding_kb_ingest",
    "embedding_kb_search",
    "embedding_memory_write",
    "embedding_memory_search",
    "embedding_memory_dedup",
)


def upgrade() -> None:
    purpose_sql = ", ".join(f"'{purpose}'" for purpose in _PURPOSES)
    op.create_table(
        "ai_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "cache_read_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "cache_write_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("output_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("requests", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"purpose IN ({purpose_sql})",
            name="ai_usage_events_purpose_check",
        ),
        sa.CheckConstraint("input_tokens >= 0", name="ai_usage_events_input_tokens_check"),
        sa.CheckConstraint(
            "cache_read_tokens >= 0", name="ai_usage_events_cache_read_tokens_check"
        ),
        sa.CheckConstraint(
            "cache_write_tokens >= 0", name="ai_usage_events_cache_write_tokens_check"
        ),
        sa.CheckConstraint("output_tokens >= 0", name="ai_usage_events_output_tokens_check"),
        sa.CheckConstraint("requests >= 0", name="ai_usage_events_requests_check"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_usage_events_workspace_occurred",
        "ai_usage_events",
        ["workspace_id", "occurred_at"],
    )
    predicate = "workspace_id = current_setting('app.current_workspace_id', true)::uuid"
    op.execute(sa.text('ALTER TABLE "ai_usage_events" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('ALTER TABLE "ai_usage_events" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            'CREATE POLICY "ai_usage_events_tenant_isolation" ON "ai_usage_events" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
    )
    op.execute(sa.text("GRANT SELECT, INSERT ON ai_usage_events TO praxis_app"))
    op.execute(sa.text("REVOKE UPDATE, DELETE ON ai_usage_events FROM praxis_app"))


def downgrade() -> None:
    op.drop_index("ix_ai_usage_events_workspace_occurred", table_name="ai_usage_events")
    op.drop_table("ai_usage_events")
