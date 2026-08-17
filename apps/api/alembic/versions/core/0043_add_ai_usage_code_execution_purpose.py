"""Add code execution to the AI usage purpose vocabulary.

Revision ID: core_0043
Revises: core_0042
"""

from alembic import op

revision = "core_0043"
down_revision = "core_0042"
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
    "embedding_kb_ingest",
    "embedding_kb_search",
    "embedding_memory_write",
    "embedding_memory_search",
    "embedding_memory_dedup",
)
_PURPOSES_AFTER = (*_PURPOSES_BEFORE[:8], "code_execution", *_PURPOSES_BEFORE[8:])


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
    """Allow provider-native code-execution helper usage rows."""
    _replace_purpose_check(_PURPOSES_AFTER)


def downgrade() -> None:
    """Restore the previous closed purpose vocabulary."""
    op.execute("DELETE FROM ai_usage_events WHERE purpose = 'code_execution'")
    _replace_purpose_check(_PURPOSES_BEFORE)
