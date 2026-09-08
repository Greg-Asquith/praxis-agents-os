# apps/api/services/agents/runtime/delegation/results.py

"""Delegate run result builders."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_COMPLETED, is_terminal
from services.agents.runtime.delegation.constants import (
    DELEGATE_NOT_ALLOWED_ERROR_CODE,
    DELEGATE_NOT_ALLOWED_ERROR_MESSAGE,
    DELEGATE_OUTPUT_PREVIEW_MAX_LENGTH,
)
from services.agents.runtime.delegation.schemas import DelegateRunResult
from services.agents.runtime.delegation.utils import truncate


def completed_or_failed_result(
    *,
    agent_name: str,
    run: AgentRun,
    conversation_id: UUID,
    output: Any,
) -> DelegateRunResult:
    if run.status == RUN_STATUS_COMPLETED:
        output_preview, truncated = truncate(
            str(output) if output is not None else "",
            DELEGATE_OUTPUT_PREVIEW_MAX_LENGTH,
        )
        return DelegateRunResult(
            status="completed",
            agent_id=run.agent_id,
            agent_name=agent_name,
            run_id=run.id,
            conversation_id=conversation_id,
            output=output_preview,
            truncated=truncated,
        )

    return DelegateRunResult(
        status="failed",
        agent_id=run.agent_id,
        agent_name=agent_name,
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

    await session.refresh(child_run, with_for_update=True)
    if not is_terminal(child_run.status):
        await fail_agent_run(
            session,
            child_run,
            error_code=DELEGATE_NOT_ALLOWED_ERROR_CODE,
            error_message=DELEGATE_NOT_ALLOWED_ERROR_MESSAGE,
        )
    await session.commit()
    if child_run.status != RUN_STATUS_COMPLETED:
        return completed_or_failed_result(
            agent_name=agent_name,
            run=child_run,
            conversation_id=conversation_id,
            output=None,
        )
    # Target visibility is required to return completed output.
    return DelegateRunResult(
        status="failed",
        agent_id=child_run.agent_id,
        agent_name=agent_name,
        run_id=child_run.id,
        conversation_id=conversation_id,
        error=DELEGATE_NOT_ALLOWED_ERROR_MESSAGE,
    )
