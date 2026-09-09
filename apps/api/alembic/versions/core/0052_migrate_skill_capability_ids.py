"""Migrate persisted skill capability IDs.

Revision ID: core_0052
Revises: core_0051
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0052"
down_revision = "core_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Replace the reserved delimiter in saved skill loads before workers start."""
    _migrate_ids("skill:", "skill-")


def downgrade() -> None:
    """Restore the skill identifiers expected by the previous runtime."""
    _migrate_ids("skill-", "skill:")


def _migrate_ids(old_prefix: str, new_prefix: str) -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION pg_temp.rewrite_skill_capability_ids(
            history jsonb, old_prefix text, new_prefix text
        ) RETURNS jsonb LANGUAGE plpgsql AS $$
        DECLARE
            message jsonb;
            part jsonb;
            args jsonb;
            capability_id text;
            message_index integer;
            part_index integer;
        BEGIN
            IF jsonb_typeof(history) IS DISTINCT FROM 'array' THEN
                RETURN history;
            END IF;
            FOR message, message_index IN
                SELECT value, ordinality - 1
                FROM jsonb_array_elements(history) WITH ORDINALITY
            LOOP
                IF message->>'kind' IS DISTINCT FROM 'response'
                    OR jsonb_typeof(message->'parts') IS DISTINCT FROM 'array' THEN
                    CONTINUE;
                END IF;
                FOR part, part_index IN
                    SELECT value, ordinality - 1
                    FROM jsonb_array_elements(message->'parts') WITH ORDINALITY
                LOOP
                    IF part->>'part_kind' IS DISTINCT FROM 'tool-call'
                        OR part->>'tool_kind' IS DISTINCT FROM 'capability-load' THEN
                        CONTINUE;
                    END IF;
                    args := part->'args';
                    IF jsonb_typeof(args) = 'string' THEN
                        BEGIN
                            args := (args #>> '{}')::jsonb;
                        EXCEPTION WHEN invalid_text_representation THEN
                            CONTINUE;
                        END;
                    END IF;
                    capability_id := args->>'id';
                    IF jsonb_typeof(args) IS DISTINCT FROM 'object'
                        OR capability_id IS NULL
                        OR capability_id !~ (
                            '^' || old_prefix ||
                            '[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$'
                        ) THEN
                        CONTINUE;
                    END IF;
                    args := jsonb_set(args, '{id}', to_jsonb(
                        new_prefix || substring(capability_id FROM length(old_prefix) + 1)
                    ));
                    IF jsonb_typeof(part->'args') = 'string' THEN
                        args := to_jsonb(args::text);
                    END IF;
                    history := jsonb_set(history,
                        ARRAY[message_index::text, 'parts', part_index::text, 'args'], args
                    );
                END LOOP;
            END LOOP;
            RETURN history;
        END;
        $$
    """)
    for statement in (
        """
            WITH rewritten AS MATERIALIZED (
                SELECT id, pg_temp.rewrite_skill_capability_ids(
                    jsonb_build_array(parts), :old_prefix, :new_prefix
                )->0 AS parts
                FROM conversation_messages
                WHERE parts::text LIKE :pattern
            )
            UPDATE conversation_messages SET parts = rewritten.parts
            FROM rewritten
            WHERE conversation_messages.id = rewritten.id
                AND conversation_messages.parts IS DISTINCT FROM rewritten.parts
        """,
        """
            WITH rewritten AS MATERIALIZED (
                SELECT id, jsonb_set(metadata, '{approval_state,message_history}',
                    pg_temp.rewrite_skill_capability_ids(
                        metadata #> '{approval_state,message_history}', :old_prefix, :new_prefix
                    )
                ) AS metadata
                FROM agent_runs
                WHERE (metadata #> '{approval_state,message_history}')::text LIKE :pattern
            )
            UPDATE agent_runs SET metadata = rewritten.metadata
            FROM rewritten
            WHERE agent_runs.id = rewritten.id
                AND agent_runs.metadata IS DISTINCT FROM rewritten.metadata
        """,
    ):
        op.execute(
            sa.text(statement).bindparams(
                old_prefix=old_prefix, new_prefix=new_prefix, pattern=f"%{old_prefix}%"
            ),
        )
    op.execute("DROP FUNCTION pg_temp.rewrite_skill_capability_ids(jsonb, text, text)")
