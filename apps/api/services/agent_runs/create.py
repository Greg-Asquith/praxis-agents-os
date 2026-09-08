# apps/api/services/agent_runs/create.py

"""Create a generic agent run."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError, CustomValueError
from models.agent_run import AgentRun
from services.agent_runs.domain import ALL_RUN_TRIGGERS, RUN_STATUS_PENDING, RUN_STATUS_RUNNING
from services.agent_runs.execution_state import require_execution_owner
from services.agent_runs.settle_run_family import lock_run_family
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
    parent_run_id: UUID | None = None,
    parent_owner_instance_id: str | None = None,
    delegation_depth: int = 0,
) -> AgentRun:
    """Insert a pending run for one agent turn and return it (flushed, not committed)."""
    if trigger not in ALL_RUN_TRIGGERS:
        raise CustomValueError(f"Unknown agent run trigger: {trigger!r}")
    if delegation_depth < 0:
        raise CustomValueError("Agent run delegation_depth must be non-negative")
    await validate_run_context(
        db,
        conversation_id=conversation_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
        user_id=user_id,
    )

    if parent_run_id is not None:
        family = await lock_run_family(db, run_id=parent_run_id)
        if (
            not family
            or family[0].id != parent_run_id
            or family[0].workspace_id != workspace_id
            or family[0].user_id != user_id
            or family[0].status not in {RUN_STATUS_PENDING, RUN_STATUS_RUNNING}
        ):
            raise ConflictError(
                "Parent run is no longer executable", conflicting_resource="agent_run"
            )
        if parent_owner_instance_id is not None:
            require_execution_owner(family[0], parent_owner_instance_id)

    run = AgentRun(
        conversation_id=conversation_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
        user_id=user_id,
        trigger=trigger,
        status=RUN_STATUS_PENDING,
        model_name=model_name,
        metadata_json=metadata,
        parent_run_id=parent_run_id,
        delegation_depth=delegation_depth,
    )
    db.add(run)
    await db.flush()
    return run
