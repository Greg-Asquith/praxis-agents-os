"""add integration event receipt tables

Revision ID: core_0018
Revises: core_0017
Create Date: 2026-07-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "core_0018"
down_revision: str | Sequence[str] | None = "core_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        "integration_webhooks",
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("external_resource_id", sa.String(length=255), nullable=False),
        sa.Column("receipt_id", sa.String(length=64), nullable=False),
        sa.Column("external_webhook_id", sa.String(length=255), nullable=False),
        sa.Column("secret_provider", sa.String(length=32), nullable=False),
        sa.Column("secret_name", sa.String(length=255), nullable=False),
        sa.Column("secret_version", sa.String(length=64), nullable=False),
        sa.Column("payload_cursor", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'error')",
            name="ck_integration_webhooks_status",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["integration_connections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["integration_resources.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_id"),
        sa.UniqueConstraint(
            "provider_key",
            "external_webhook_id",
            name="uq_integration_webhooks_provider_external",
        ),
    )
    op.create_index(
        "ix_integration_webhooks_connection_status",
        "integration_webhooks",
        ["connection_id", "status"],
    )
    op.create_index(
        "ix_integration_webhooks_refresh_due",
        "integration_webhooks",
        ["status", "expires_at"],
        postgresql_where=sa.text("status = 'active' AND expires_at IS NOT NULL"),
    )

    op.create_table(
        "integration_events",
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("webhook_id", sa.UUID(), nullable=False),
        sa.Column("external_event_id", sa.String(length=255), nullable=False),
        sa.Column("external_resource_id", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'received'"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discard_reason", sa.String(length=128), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('received', 'processed', 'discarded')",
            name="ck_integration_events_status",
        ),
        sa.CheckConstraint(
            "char_length(payload_digest) = 64",
            name="ck_integration_events_payload_digest",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["integration_connections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["webhook_id"],
            ["integration_webhooks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_key",
            "dedup_key",
            name="uq_integration_events_provider_dedup",
        ),
    )
    op.create_index(
        "ix_integration_events_status_received",
        "integration_events",
        ["status", "received_at"],
    )
    op.create_index(
        "ix_integration_events_connection_received",
        "integration_events",
        ["connection_id", "received_at"],
    )
    op.create_index(
        "ix_integration_events_webhook_received",
        "integration_events",
        ["webhook_id", "received_at"],
    )

    op.drop_constraint("agent_runs_trigger_check", "agent_runs", type_="check")
    op.create_check_constraint(
        "agent_runs_trigger_check",
        "agent_runs",
        "trigger IN ('interactive', 'scheduled', 'delegated', 'event')",
    )
    op.drop_constraint("conversations_source_check", "conversations", type_="check")
    op.create_check_constraint(
        "conversations_source_check",
        "conversations",
        "source IN ('direct', 'scheduled', 'delegated', 'event')",
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_constraint("conversations_source_check", "conversations", type_="check")
    op.create_check_constraint(
        "conversations_source_check",
        "conversations",
        "source IN ('direct', 'scheduled', 'delegated')",
    )
    op.drop_constraint("agent_runs_trigger_check", "agent_runs", type_="check")
    op.create_check_constraint(
        "agent_runs_trigger_check",
        "agent_runs",
        "trigger IN ('interactive', 'scheduled', 'delegated')",
    )
    op.drop_index(
        "ix_integration_events_webhook_received",
        table_name="integration_events",
    )
    op.drop_index(
        "ix_integration_events_connection_received",
        table_name="integration_events",
    )
    op.drop_index(
        "ix_integration_events_status_received",
        table_name="integration_events",
    )
    op.drop_table("integration_events")
    op.drop_index(
        "ix_integration_webhooks_refresh_due",
        table_name="integration_webhooks",
    )
    op.drop_index(
        "ix_integration_webhooks_connection_status",
        table_name="integration_webhooks",
    )
    op.drop_table("integration_webhooks")
