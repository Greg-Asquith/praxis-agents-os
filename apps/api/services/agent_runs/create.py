# apps/api/services/agent_runs/create.py

"""Create a generic agent run."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import CustomValueError
from models.agent_run import AgentRun
from services.agent_runs.domain import ALL_RUN_TRIGGERS, RUN_STATUS_PENDING
from services.agent_runs.utils import validate_run_context


async def create_agent_run(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    agent_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    trigger: str,
    model_name: str | None = None,
    metadata: dict | None = None,
) -> AgentRun:
    """Insert a pending run for one agent turn and return it (flushed, not committed)."""
    if trigger not in ALL_RUN_TRIGGERS:
        raise CustomValueError(f"Unknown agent run trigger: {trigger!r}")
    await validate_run_context(
        db,
        conversation_id=conversation_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
        user_id=user_id,
    )

    run = AgentRun(
        conversation_id=conversation_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
        user_id=user_id,
        trigger=trigger,
        status=RUN_STATUS_PENDING,
        model_name=model_name,
        metadata_json=metadata,
    )
    db.add(run)
    await db.flush()
    return run
