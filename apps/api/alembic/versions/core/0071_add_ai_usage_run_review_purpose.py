# apps/api/alembic/versions/core/0071_add_ai_usage_run_review_purpose.py

"""Add the progress review usage purpose.

Revision ID: core_0071
Revises: core_0070
"""

from alembic import op

revision = "core_0071"
down_revision = "core_0070"
branch_labels = None
depends_on = None

_PURPOSES_BEFORE = (
    "agent_run",
    "conversation_naming",
    "history_summary",
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
_PURPOSES_AFTER = (*_PURPOSES_BEFORE[:3], "run_review", *_PURPOSES_BEFORE[3:])


def _replace_purpose_check(purposes: tuple[str, ...]) -> None:
    values = ", ".join(f"'{purpose}'" for purpose in purposes)
    op.drop_constraint(
        "ai_usage_events_purpose_check",
        "ai_usage_events",
        type_="check",
    )
    op.create_check_constraint(
        "ai_usage_events_purpose_check",
        "ai_usage_events",
        f"purpose IN ({values})",
    )


def upgrade() -> None:
    """Allow progress review usage rows."""
    _replace_purpose_check(_PURPOSES_AFTER)


def downgrade() -> None:
    """Restore the previous closed purpose vocabulary."""
    op.execute("DELETE FROM ai_usage_events WHERE purpose = 'run_review'")
    _replace_purpose_check(_PURPOSES_BEFORE)
