# apps/api/alembic/versions/core/0088_add_ai_usage_purposes.py

"""Moves AI usage purposes from a check constraint into their own table.

A deployment adds its own purposes with rows from its app migrations, so core
migrations no longer rewrite a list that drops them.

Revision ID: core_0088
Revises: core_0087
"""

import sqlalchemy as sa

from alembic import op

revision = "core_0088"
down_revision = "core_0087"
branch_labels = None
depends_on = None

_PURPOSES = (
    ("agent_run", "Agent conversations"),
    ("conversation_naming", "Conversation housekeeping"),
    ("history_summary", "Conversation housekeeping"),
    ("run_review", "Progress checks"),
    ("memory_dreaming", "Learning from conversations"),
    ("kb_annotation", "Document processing"),
    ("classification", "Classification"),
    ("web_search", "Web research"),
    ("web_fetch", "Web research"),
    ("image_generation", "Image creation"),
    ("code_execution", "Code execution"),
    ("video_understanding", "Video understanding"),
    ("video_generation", "Video creation"),
    ("video_transcription", "Transcription"),
    ("embedding_kb_ingest", "Search & document indexing"),
    ("embedding_kb_search", "Search & document indexing"),
    ("embedding_memory_write", "Search & document indexing"),
    ("embedding_memory_search", "Search & document indexing"),
    ("embedding_memory_dedup", "Search & document indexing"),
)


def upgrade() -> None:
    purposes = op.create_table(
        "ai_usage_purposes",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.bulk_insert(purposes, [{"key": key, "label": label} for key, label in _PURPOSES])
    # Keeps purposes a deployment added to the old check, so its usage rows still match.
    op.execute(
        "INSERT INTO ai_usage_purposes (key, label) "
        "SELECT DISTINCT purpose, initcap(replace(purpose, '_', ' ')) FROM ai_usage_events "
        "ON CONFLICT (key) DO NOTHING"
    )
    # Only migrations change purposes; the runtime role reads them.
    op.execute("REVOKE INSERT, UPDATE, DELETE ON ai_usage_purposes FROM praxis_app")
    op.execute("GRANT SELECT ON ai_usage_purposes TO praxis_app")
    op.drop_constraint("ai_usage_events_purpose_check", "ai_usage_events", type_="check")
    op.create_foreign_key(
        "ai_usage_events_purpose_fkey",
        "ai_usage_events",
        "ai_usage_purposes",
        ["purpose"],
        ["key"],
    )


def downgrade() -> None:
    op.drop_constraint("ai_usage_events_purpose_fkey", "ai_usage_events", type_="foreignkey")
    core = ", ".join(f"'{key}'" for key, _ in _PURPOSES)
    op.execute(f"DELETE FROM ai_usage_events WHERE purpose NOT IN ({core})")
    op.create_check_constraint(
        "ai_usage_events_purpose_check", "ai_usage_events", f"purpose IN ({core})"
    )
    op.drop_table("ai_usage_purposes")
