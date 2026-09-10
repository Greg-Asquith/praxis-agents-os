"""Adds platform-owned usage and bounded ingestion admission counters.

Revision ID: core_0055
Revises: core_0054
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "core_0055"
down_revision: str | Sequence[str] | None = "core_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("ai_usage_events", "embedding_token_usage")
_WORKSPACE_ID = "NULLIF(current_setting('app.current_workspace_id', true), '')::uuid"


def upgrade() -> None:
    """Adds explicit ownership while retaining workspace-only runtime access."""
    for table in _TABLES:
        op.add_column(
            table, sa.Column("scope", sa.String(16), server_default="workspace", nullable=False)
        )
        op.alter_column(table, "workspace_id", existing_type=sa.UUID(), nullable=True)
        op.create_check_constraint(
            f"{table}_scope_owner_check",
            table,
            "(scope = 'workspace' AND workspace_id IS NOT NULL) OR "
            "(scope = 'platform' AND workspace_id IS NULL)",
        )
        predicate = f"scope = 'workspace' AND workspace_id = {_WORKSPACE_ID}"
        op.execute(
            sa.text(
                f'ALTER POLICY "{table}_tenant_isolation" ON "{table}" '
                f"USING ({predicate}) WITH CHECK ({predicate})"
            )
        )
    op.create_check_constraint(
        "ai_usage_events_platform_context_check",
        "ai_usage_events",
        "scope = 'workspace' OR (purpose IN ('kb_annotation', 'embedding_kb_ingest') "
        "AND agent_id IS NULL AND run_id IS NULL AND conversation_id IS NULL)",
    )
    op.create_index(
        "uq_embedding_token_usage_platform_month",
        "embedding_token_usage",
        ["period_month"],
        unique=True,
        postgresql_where=sa.text("scope = 'platform'"),
    )
    op.create_table(
        "platform_ingestion_usage",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("requests_reserved", sa.BigInteger(), server_default="0", nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period_month", name="uq_platform_ingestion_usage_month"),
        sa.CheckConstraint(
            "requests_reserved >= 0", name="ck_platform_ingestion_usage_requests_nonnegative"
        ),
    )
    op.execute("ALTER TABLE platform_ingestion_usage ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform_ingestion_usage FORCE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON platform_ingestion_usage FROM praxis_app")


def downgrade() -> None:
    """Restores workspace ownership only after platform accounting is removed."""
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM ai_usage_events WHERE scope = 'platform')
               OR EXISTS (SELECT 1 FROM embedding_token_usage WHERE scope = 'platform')
               OR EXISTS (SELECT 1 FROM platform_ingestion_usage) THEN
                RAISE EXCEPTION 'Remove platform accounting through maintenance before downgrading';
            END IF;
        END $$
    """)
    op.drop_table("platform_ingestion_usage")
    op.drop_index("uq_embedding_token_usage_platform_month", table_name="embedding_token_usage")
    op.drop_constraint("ai_usage_events_platform_context_check", "ai_usage_events", type_="check")
    for table in _TABLES:
        predicate = f"workspace_id = {_WORKSPACE_ID}"
        op.execute(
            sa.text(
                f'ALTER POLICY "{table}_tenant_isolation" ON "{table}" '
                f"USING ({predicate}) WITH CHECK ({predicate})"
            )
        )
        op.drop_constraint(f"{table}_scope_owner_check", table, type_="check")
        op.drop_column(table, "scope")
        op.alter_column(table, "workspace_id", existing_type=sa.UUID(), nullable=False)
