"""add integration core tables

Revision ID: core_0013
Revises: core_0012
Create Date: 2026-07-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "core_0013"
down_revision: str | Sequence[str] | None = "core_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_table(
        "external_credentials",
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("auth_mode", sa.String(length=32), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_type", sa.String(length=32), nullable=True),
        sa.Column("granted_scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("encryption_key_id", sa.String(length=16), nullable=True),
        sa.Column("secret_provider", sa.String(length=32), nullable=True),
        sa.Column("secret_name", sa.String(length=255), nullable=True),
        sa.Column("secret_version", sa.String(length=64), nullable=True),
        sa.Column("principal_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("external_principal_label", sa.String(length=255), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "refresh_failure_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("last_refresh_error_code", sa.String(length=64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
            "auth_mode IN ('oauth', 'api_key', 'service_account', 'system_token')",
            name="ck_external_credentials_auth_mode",
        ),
        sa.CheckConstraint(
            "(auth_mode = 'oauth' AND secret_provider IS NULL "
            "AND secret_name IS NULL AND secret_version IS NULL) OR "
            "(auth_mode <> 'oauth' AND access_token_encrypted IS NULL "
            "AND refresh_token_encrypted IS NULL AND secret_name IS NOT NULL "
            "AND secret_provider IS NOT NULL AND secret_version IS NOT NULL)",
            name="ck_external_credentials_mode_payload",
        ),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_credentials_provider_key",
        "external_credentials",
        ["provider_key"],
    )
    op.create_index(
        "ix_external_credentials_principal_fingerprint",
        "external_credentials",
        ["principal_fingerprint"],
    )
    op.create_index(
        "ix_external_credentials_deleted_at",
        "external_credentials",
        ["deleted_at"],
    )

    op.create_table(
        "integration_connections",
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("owner_workspace_id", sa.UUID(), nullable=True),
        sa.Column("credential_id", sa.UUID(), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'auth_pending'"), nullable=False
        ),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_by_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "provider_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
            "char_length(btrim(label)) > 0",
            name="ck_integration_connections_label_not_blank",
        ),
        sa.CheckConstraint(
            "num_nonnulls(owner_user_id, owner_workspace_id) = 1",
            name="ck_integration_connections_owner_xor",
        ),
        sa.CheckConstraint(
            "status IN ('auth_pending', 'discovery_pending', "
            "'needs_resource_selection', 'active', 'degraded', 'error', "
            "'revoked', 'needs_reauth')",
            name="ck_integration_connections_status",
        ),
        sa.ForeignKeyConstraint(["connected_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["credential_id"], ["external_credentials.id"]),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["owner_workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_integration_connections_provider_key",
        "integration_connections",
        ["provider_key"],
    )
    op.create_index(
        "ix_integration_connections_deleted_at",
        "integration_connections",
        ["deleted_at"],
    )
    op.create_index(
        "uq_integration_connections_credential",
        "integration_connections",
        ["credential_id"],
        unique=True,
        postgresql_where=sa.text("deleted = false"),
    )
    op.create_index(
        "ix_integration_connections_workspace_provider",
        "integration_connections",
        ["owner_workspace_id", "provider_key"],
        postgresql_where=sa.text("deleted = false"),
    )
    op.create_index(
        "ix_integration_connections_user_provider",
        "integration_connections",
        ["owner_user_id", "provider_key"],
        postgresql_where=sa.text("deleted = false"),
    )

    op.create_table(
        "integration_resources",
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("parent_external_id", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "availability",
            sa.String(length=16),
            server_default=sa.text("'available'"),
            nullable=False,
        ),
        sa.Column("writable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "permissions_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
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
            "availability IN ('available', 'unavailable', 'removed')",
            name="ck_integration_resources_availability",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["integration_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "resource_type",
            "external_id",
            name="uq_integration_resources_connection_external",
        ),
    )
    op.create_index(
        "ix_integration_resources_connection_id",
        "integration_resources",
        ["connection_id"],
    )
    op.create_index(
        "ix_integration_resources_deleted_at",
        "integration_resources",
        ["deleted_at"],
    )
    op.create_index(
        "ix_integration_resources_connection_enabled",
        "integration_resources",
        ["connection_id", "enabled"],
        postgresql_where=sa.text("deleted = false"),
    )

    op.create_table(
        "integration_discovery_runs",
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column(
            "job_id",
            sa.UUID(),
            nullable=True,
            comment="No FK: discovery history outlives the jobs retention window.",
        ),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'running'"), nullable=False
        ),
        sa.Column("resources_found", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("resources_added", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("resources_removed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("resources_unchanged", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_integration_discovery_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["integration_connections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_integration_discovery_runs_connection_id",
        "integration_discovery_runs",
        ["connection_id"],
    )
    op.create_index(
        "ix_integration_discovery_runs_connection_created",
        "integration_discovery_runs",
        ["connection_id", "created_at"],
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index(
        "ix_integration_discovery_runs_connection_created",
        table_name="integration_discovery_runs",
    )
    op.drop_index(
        "ix_integration_discovery_runs_connection_id",
        table_name="integration_discovery_runs",
    )
    op.drop_table("integration_discovery_runs")

    op.drop_index(
        "ix_integration_resources_connection_enabled",
        table_name="integration_resources",
    )
    op.drop_index("ix_integration_resources_deleted_at", table_name="integration_resources")
    op.drop_index("ix_integration_resources_connection_id", table_name="integration_resources")
    op.drop_table("integration_resources")

    op.drop_index(
        "ix_integration_connections_user_provider",
        table_name="integration_connections",
    )
    op.drop_index(
        "ix_integration_connections_workspace_provider",
        table_name="integration_connections",
    )
    op.drop_index(
        "uq_integration_connections_credential",
        table_name="integration_connections",
    )
    op.drop_index("ix_integration_connections_deleted_at", table_name="integration_connections")
    op.drop_index("ix_integration_connections_provider_key", table_name="integration_connections")
    op.drop_table("integration_connections")

    op.drop_index("ix_external_credentials_deleted_at", table_name="external_credentials")
    op.drop_index(
        "ix_external_credentials_principal_fingerprint",
        table_name="external_credentials",
    )
    op.drop_index("ix_external_credentials_provider_key", table_name="external_credentials")
    op.drop_table("external_credentials")
