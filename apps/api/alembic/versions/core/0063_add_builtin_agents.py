"""Adds the built-in agent and provisions it in every existing workspace.

Each provisioned agent gets a system-actor creation audit event. Downgrade keeps
the rows, with their history, as ordinary agents with a stored name.

Revision ID: core_0063
Revises: core_0062
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0063"
down_revision = "core_0062"
branch_labels = None
depends_on = None

# Frozen copy; later releases may change the application constant.
_DESCRIPTION = (
    "Your workspace's own agent. It gets work done with every tool your "
    "workspace allows, hands work to your other agents, and can answer "
    "questions about the platform."
)
# Earlier releases require instructions, and the code-owned base does not survive a downgrade.
_DOWNGRADE_INSTRUCTIONS = (
    "Help the people in this workspace get their work done with the tools the workspace allows."
)


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "uq_agents_builtin_workspace",
        "agents",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_builtin AND NOT deleted"),
    )
    # The built-in agent's name is derived at read time, so its row stores none.
    op.alter_column("agents", "name", existing_type=sa.String(), nullable=True)
    op.create_check_constraint("ck_agents_builtin_name", "agents", "(name IS NULL) = is_builtin")

    # Migrations run as the owning role, whose maintenance policy passes row-level security.
    op.execute(
        sa.text(
            """
            WITH inserted AS (
                INSERT INTO agents (
                    id, name, slug, description, instructions, workspace_id, created_by,
                    all_tools, is_builtin, metadata, created_at, updated_at
                )
                SELECT
                    gen_random_uuid(),
                    NULL,
                    free_slug.slug,
                    :description,
                    '',
                    workspaces.id,
                    owner.user_id,
                    true,
                    true,
                    '{"identity_color": 1}'::jsonb,
                    now(),
                    now()
                FROM workspaces
                JOIN LATERAL (
                    SELECT memberships.user_id
                    FROM workspace_memberships AS memberships
                    WHERE memberships.workspace_id = workspaces.id
                      AND memberships.role = 'owner'
                      AND NOT memberships.deleted
                    ORDER BY memberships.created_at
                    LIMIT 1
                ) AS owner ON true
                -- create_agent's suffix scheme; deleted agents still hold their slugs.
                JOIN LATERAL (
                    SELECT candidate.slug
                    FROM generate_series(
                        1,
                        1 + (SELECT count(*) FROM agents WHERE agents.workspace_id = workspaces.id)
                    ) AS n
                    CROSS JOIN LATERAL (
                        SELECT CASE WHEN n = 1 THEN 'workspace-agent'
                                    ELSE 'workspace-agent-' || n END AS slug
                    ) AS candidate
                    WHERE NOT EXISTS (
                        SELECT 1 FROM agents AS taken
                        WHERE taken.workspace_id = workspaces.id
                          AND taken.slug = candidate.slug
                    )
                    ORDER BY n
                    LIMIT 1
                ) AS free_slug ON true
                WHERE NOT workspaces.deleted
                  AND NOT EXISTS (
                      SELECT 1 FROM agents AS existing
                      WHERE existing.workspace_id = workspaces.id
                        AND existing.is_builtin
                        AND NOT existing.deleted
                  )
                RETURNING id, workspace_id, slug
            )
            INSERT INTO audit_events (
                id, workspace_id, occurred_at, action, resource_type, resource_id, status,
                summary, actor_type, actor_id, actor_display, details, created_at
            )
            SELECT
                gen_random_uuid(),
                inserted.workspace_id,
                now(),
                'create',
                'agent',
                inserted.id::text,
                'success',
                'Platform migration create agent ' || inserted.id || ': success',
                'system',
                'migration:core_0063',
                'Platform migration',
                jsonb_build_object('slug', inserted.slug, 'builtin', true),
                now()
            FROM inserted
            """
        ).bindparams(description=_DESCRIPTION)
    )


def downgrade() -> None:
    op.drop_constraint("ck_agents_builtin_name", "agents", type_="check")
    # Store the derived name so runs, conversations, and schedules keep their agent.
    op.execute(
        sa.text(
            """
            UPDATE agents
            SET
                name = CASE
                    WHEN workspaces.is_personal THEN coalesce(
                        (
                            SELECT nullif(split_part(btrim(users.display_name), ' ', 1), '')
                            FROM workspace_memberships AS memberships
                            JOIN users ON users.id = memberships.user_id
                            WHERE memberships.workspace_id = agents.workspace_id
                              AND memberships.role = 'owner'
                              AND NOT memberships.deleted
                            ORDER BY memberships.created_at
                            LIMIT 1
                        ) || '''s Agent',
                        'My Agent'
                    )
                    ELSE workspaces.name || ' Agent'
                END,
                instructions = CASE
                    WHEN btrim(agents.instructions) = '' THEN :instructions
                    ELSE agents.instructions
                END
            FROM workspaces
            WHERE workspaces.id = agents.workspace_id
              AND agents.is_builtin
            """
        ).bindparams(instructions=_DOWNGRADE_INSTRUCTIONS)
    )
    op.alter_column("agents", "name", existing_type=sa.String(), nullable=False)
    op.drop_index("uq_agents_builtin_workspace", table_name="agents")
    op.drop_column("agents", "is_builtin")
