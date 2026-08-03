"""add workspace row-level security

Revision ID: core_0032
Revises: core_0031
Create Date: 2026-08-03 00:00:00.000000

Global tables intentionally remain outside RLS: users, sessions, user_auth,
password_reset_tokens, security_events, rate_limit_attempts, workspaces,
workspace_memberships, workspace_invitations, asset_uploads, and jobs.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "core_0032"
down_revision: str | Sequence[str] | None = "core_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DIRECT_TABLES = (
    "agents",
    "agent_schedules",
    "agent_schedule_runs",
    "agent_runs",
    "agent_memories",
    "conversations",
    "conversation_todos",
    "conversation_messages",
    "conversation_summaries",
    "artifacts",
    "artifact_revisions",
    "artifact_shares",
    "files",
    "file_revisions",
    "file_references",
    "file_uploads",
    "kb_documents",
    "kb_chunks",
    "skills",
    "embedding_token_usage",
    "scratch_entries",
    "workspace_tool_settings",
    "integration_context_groups",
    "active_context_selections",
    "audit_events",
)

_INDIRECT_POLICIES = {
    "integration_oauth_states": """
        EXISTS (
            SELECT 1 FROM integration_connections AS connection
            WHERE connection.id = integration_oauth_states.connection_id
              AND (
                  connection.owner_workspace_id =
                      current_setting('app.current_workspace_id', true)::uuid
                  OR connection.owner_user_id =
                      current_setting('app.current_user_id', true)::uuid
              )
        )
    """,
    "integration_resources": """
        EXISTS (
            SELECT 1 FROM integration_connections AS connection
            WHERE connection.id = integration_resources.connection_id
              AND (
                  connection.owner_workspace_id =
                      current_setting('app.current_workspace_id', true)::uuid
                  OR connection.owner_user_id =
                      current_setting('app.current_user_id', true)::uuid
              )
        )
    """,
    "integration_discovery_runs": """
        EXISTS (
            SELECT 1 FROM integration_connections AS connection
            WHERE connection.id = integration_discovery_runs.connection_id
              AND (
                  connection.owner_workspace_id =
                      current_setting('app.current_workspace_id', true)::uuid
                  OR connection.owner_user_id =
                      current_setting('app.current_user_id', true)::uuid
              )
        )
    """,
    "integration_webhooks": """
        EXISTS (
            SELECT 1 FROM integration_connections AS connection
            WHERE connection.id = integration_webhooks.connection_id
              AND (
                  connection.owner_workspace_id =
                      current_setting('app.current_workspace_id', true)::uuid
                  OR connection.owner_user_id =
                      current_setting('app.current_user_id', true)::uuid
              )
        )
    """,
    "integration_events": """
        EXISTS (
            SELECT 1 FROM integration_connections AS connection
            WHERE connection.id = integration_events.connection_id
              AND (
                  connection.owner_workspace_id =
                      current_setting('app.current_workspace_id', true)::uuid
                  OR connection.owner_user_id =
                      current_setting('app.current_user_id', true)::uuid
              )
        )
    """,
    "integration_table_schemas": """
        EXISTS (
            SELECT 1
            FROM integration_resources AS resource
            JOIN integration_connections AS connection
              ON connection.id = resource.connection_id
            WHERE resource.id = integration_table_schemas.resource_id
              AND (
                  connection.owner_workspace_id =
                      current_setting('app.current_workspace_id', true)::uuid
                  OR connection.owner_user_id =
                      current_setting('app.current_user_id', true)::uuid
              )
        )
    """,
    "integration_context_group_members": """
        EXISTS (
            SELECT 1 FROM integration_context_groups AS context_group
            WHERE context_group.id = integration_context_group_members.group_id
              AND context_group.workspace_id =
                  current_setting('app.current_workspace_id', true)::uuid
        )
    """,
}

_DUAL_OWNER_POLICIES = {
    "external_credentials": """
        owner_workspace_id = current_setting('app.current_workspace_id', true)::uuid
        OR owner_user_id = current_setting('app.current_user_id', true)::uuid
    """,
    "integration_connections": """
        owner_workspace_id = current_setting('app.current_workspace_id', true)::uuid
        OR owner_user_id = current_setting('app.current_user_id', true)::uuid
    """,
    "notifications": """
        workspace_id = current_setting('app.current_workspace_id', true)::uuid
        OR recipient_user_id = current_setting('app.current_user_id', true)::uuid
    """,
}


def _policy_name(table_name: str) -> str:
    return f"{table_name}_tenant_isolation"


def _enable_policy(table_name: str, predicate: str) -> None:
    policy_name = _policy_name(table_name)
    op.execute(sa.text(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            f'CREATE POLICY "{policy_name}" ON "{table_name}" '
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
    )


def upgrade() -> None:
    """Add tenant columns, runtime privileges, and fail-closed RLS policies."""
    op.execute(
        sa.text(
            """
            DO $role$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'praxis_app') THEN
                    CREATE ROLE praxis_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                        NOINHERIT NOBYPASSRLS;
                END IF;
            END
            $role$;
            """
        )
    )
    op.execute(sa.text("GRANT praxis_app TO CURRENT_USER"))
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS app"))

    op.add_column(
        "external_credentials",
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "external_credentials",
        sa.Column("owner_workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE external_credentials AS credential
            SET owner_user_id = connection.owner_user_id,
                owner_workspace_id = connection.owner_workspace_id
            FROM integration_connections AS connection
            WHERE connection.credential_id = credential.id
            """
        )
    )
    op.create_check_constraint(
        "ck_external_credentials_owner_xor",
        "external_credentials",
        "num_nonnulls(owner_user_id, owner_workspace_id) = 1",
    )
    op.create_index(
        "ix_external_credentials_owner_user_id",
        "external_credentials",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_external_credentials_owner_workspace_id",
        "external_credentials",
        ["owner_workspace_id"],
    )

    op.add_column(
        "conversation_messages",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "conversation_summaries",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE conversation_messages AS message
            SET workspace_id = conversation.workspace_id
            FROM conversations AS conversation
            WHERE conversation.id = message.conversation_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE conversation_summaries AS summary
            SET workspace_id = conversation.workspace_id
            FROM conversations AS conversation
            WHERE conversation.id = summary.conversation_id
            """
        )
    )
    op.alter_column("conversation_messages", "workspace_id", nullable=False)
    op.alter_column("conversation_summaries", "workspace_id", nullable=False)
    op.create_foreign_key(
        "fk_conversation_messages_workspace_id_workspaces",
        "conversation_messages",
        "workspaces",
        ["workspace_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_conversation_summaries_workspace_id_workspaces",
        "conversation_summaries",
        "workspaces",
        ["workspace_id"],
        ["id"],
    )
    op.create_index(
        "ix_conversation_messages_workspace_id",
        "conversation_messages",
        ["workspace_id"],
    )
    op.create_index(
        "ix_conversation_summaries_workspace_id",
        "conversation_summaries",
        ["workspace_id"],
    )
    op.create_index(
        "ix_active_context_selections_workspace_id",
        "active_context_selections",
        ["workspace_id"],
    )

    direct_predicate = "workspace_id = current_setting('app.current_workspace_id', true)::uuid"
    for table_name in _DIRECT_TABLES:
        _enable_policy(table_name, direct_predicate)
    for table_name, predicate in _DUAL_OWNER_POLICIES.items():
        _enable_policy(table_name, predicate)
    for table_name, predicate in _INDIRECT_POLICIES.items():
        _enable_policy(table_name, predicate)

    op.execute(sa.text("GRANT USAGE ON SCHEMA public, app TO praxis_app"))
    op.execute(
        sa.text(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public, app TO praxis_app"
        )
    )
    op.execute(sa.text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public, app TO praxis_app"))
    op.execute(
        sa.text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public, app "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO praxis_app"
        )
    )
    op.execute(
        sa.text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public, app "
            "GRANT USAGE, SELECT ON SEQUENCES TO praxis_app"
        )
    )


def downgrade() -> None:
    """Remove workspace RLS and this database's runtime-role privileges."""
    for table_name in (*_DIRECT_TABLES, *_DUAL_OWNER_POLICIES, *_INDIRECT_POLICIES):
        op.execute(sa.text(f'DROP POLICY IF EXISTS "{_policy_name(table_name)}" ON "{table_name}"'))
        op.execute(sa.text(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY'))

    op.drop_index(
        "ix_active_context_selections_workspace_id",
        table_name="active_context_selections",
    )

    op.drop_index(
        "ix_conversation_summaries_workspace_id",
        table_name="conversation_summaries",
    )
    op.drop_index(
        "ix_conversation_messages_workspace_id",
        table_name="conversation_messages",
    )
    op.drop_constraint(
        "fk_conversation_summaries_workspace_id_workspaces",
        "conversation_summaries",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_conversation_messages_workspace_id_workspaces",
        "conversation_messages",
        type_="foreignkey",
    )
    op.drop_column("conversation_summaries", "workspace_id")
    op.drop_column("conversation_messages", "workspace_id")
    op.drop_constraint(
        "ck_external_credentials_owner_xor",
        "external_credentials",
        type_="check",
    )
    op.drop_index(
        "ix_external_credentials_owner_workspace_id",
        table_name="external_credentials",
    )
    op.drop_index(
        "ix_external_credentials_owner_user_id",
        table_name="external_credentials",
    )
    op.drop_column("external_credentials", "owner_workspace_id")
    op.drop_column("external_credentials", "owner_user_id")
    op.execute(sa.text("DROP OWNED BY praxis_app"))
    # Roles are cluster-wide and may still serve another database in the same
    # Postgres cluster (for example the local dev and test databases).
