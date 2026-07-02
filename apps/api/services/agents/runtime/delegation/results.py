# apps/api/services/agents/runtime/delegation/results.py

"""Delegate run result builders."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_COMPLETED
from services.agents.runtime.approval_state import clear_suspended_run_metadata
from services.agents.runtime.delegation.constants import (
    DELEGATE_NOT_ALLOWED_ERROR_CODE,
    DELEGATE_NOT_ALLOWED_ERROR_MESSAGE,
    DELEGATE_OUTPUT_PREVIEW_MAX_LENGTH,
)
from services.agents.runtime.delegation.schemas import DelegateRunResult
from services.agents.runtime.delegation.utils import truncate


def completed_or_failed_result(
    *,
    agent: Agent,
    run: AgentRun,
    conversation_id: UUID,
    output: Any,
) -> DelegateRunResult:
    if run.status == RUN_STATUS_COMPLETED:
        output_preview, truncated = truncate(
            str(output),
            DELEGATE_OUTPUT_PREVIEW_MAX_LENGTH,
        )
        return DelegateRunResult(
            status="completed",
            agent_id=agent.id,
            agent_name=agent.name,
            run_id=run.id,
            conversation_id=conversation_id,
            output=output_preview,
            truncated=truncated,
        )

    return DelegateRunResult(
        status="failed",
        agent_id=agent.id,
        agent_name=agent.name,
        run_id=run.id,
        conversation_id=conversation_id,
        error=run.error_message or "Delegate run did not complete.",
    )


async def fail_child_run_delegate_not_allowed(
    session: AsyncSession,
    *,
    child_run: AgentRun,
    conversation_id: UUID,
    agent_name: str,
) -> DelegateRunResult:
    from services.agent_runs.fail import fail_agent_run

    child_run.metadata_json = clear_suspended_run_metadata(child_run)
    await fail_agent_run(
        session,
        child_run,
        error_code=DELEGATE_NOT_ALLOWED_ERROR_CODE,
        error_message=DELEGATE_NOT_ALLOWED_ERROR_MESSAGE,
    )
    await session.commit()
    return DelegateRunResult(
        status="failed",
        agent_id=child_run.agent_id,
        agent_name=agent_name,
        run_id=child_run.id,
        conversation_id=conversation_id,
        error=DELEGATE_NOT_ALLOWED_ERROR_MESSAGE,
    )
