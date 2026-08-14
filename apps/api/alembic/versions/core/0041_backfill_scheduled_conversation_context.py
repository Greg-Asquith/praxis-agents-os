"""Backfill scheduled conversation active context selections.

Revision ID: core_0041
Revises: core_0040
"""

from alembic import op

SCHEDULED_CONTEXT_BACKFILL_SQL = """
INSERT INTO active_context_selections (
    id,
    conversation_id,
    workspace_id,
    integration_resource_id,
    context_group_id,
    created_at,
    updated_at
)
SELECT
    gen_random_uuid(),
    conversation.id,
    conversation.workspace_id,
    CASE
        WHEN target.value->>'type' = 'resource'
        THEN resource.id
        ELSE NULL
    END,
    CASE
        WHEN target.value->>'type' = 'context_group'
        THEN context_group.id
        ELSE NULL
    END,
    now(),
    now()
FROM conversations AS conversation
JOIN agent_schedules AS schedule
  ON schedule.id = conversation.schedule_id
 AND schedule.workspace_id = conversation.workspace_id
CROSS JOIN LATERAL jsonb_array_elements(
    CASE
        WHEN jsonb_typeof(schedule.active_context->'targets') = 'array'
        THEN schedule.active_context->'targets'
        ELSE '[]'::jsonb
    END
) AS target(value)
LEFT JOIN integration_resources AS resource
  ON target.value->>'type' = 'resource'
 AND target.value->>'integration_resource_id' = resource.id::text
LEFT JOIN integration_context_groups AS context_group
  ON target.value->>'type' = 'context_group'
 AND target.value->>'context_group_id' = context_group.id::text
 AND context_group.workspace_id = conversation.workspace_id
WHERE conversation.source = 'scheduled'
  AND conversation.deleted = false
  AND NOT EXISTS (
      SELECT 1
      FROM active_context_selections AS existing
      WHERE existing.conversation_id = conversation.id
  )
  AND (
      (target.value->>'type' = 'resource' AND resource.id IS NOT NULL)
      OR
      (target.value->>'type' = 'context_group' AND context_group.id IS NOT NULL)
  )
ON CONFLICT DO NOTHING
"""

revision = "core_0041"
down_revision = "core_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Copy schedule context into scheduled conversations that have no saved selection."""
    op.execute(SCHEDULED_CONTEXT_BACKFILL_SQL)


def downgrade() -> None:
    """Retain repaired conversation selections on downgrade."""
