# apps/api/alembic/versions/core/006_rename_agent_call_conversation_source.py

"""rename agent_call conversation source to delegated"""

from collections.abc import Sequence

from alembic import op

revision: str = "core_0006"
down_revision: str | Sequence[str] | None = "core_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("conversations_source_check", "conversations", type_="check")
    op.execute("UPDATE conversations SET source = 'delegated' WHERE source = 'agent_call'")
    op.create_check_constraint(
        "conversations_source_check",
        "conversations",
        "source IN ('direct', 'scheduled', 'delegated')",
    )


def downgrade() -> None:
    op.drop_constraint("conversations_source_check", "conversations", type_="check")
    op.execute("UPDATE conversations SET source = 'agent_call' WHERE source = 'delegated'")
    op.create_check_constraint(
        "conversations_source_check",
        "conversations",
        "source IN ('direct', 'scheduled', 'agent_call')",
    )