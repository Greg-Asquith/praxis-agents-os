# apps/api/services/agents/runtime/delegation/delegate_to_agent.py

"""Run a delegated child agent call."""

from typing import Annotated

from pydantic import Field
from pydantic_ai import RunContext
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.delegation.child_run import ChildRunTarget, run_child_agent
from services.agents.runtime.delegation.constants import DELEGATE_TASK_MAX_LENGTH
from services.agents.runtime.delegation.get_visible_delegate_agent import (
    get_visible_delegate_agent,
)
from services.agents.runtime.delegation.resume_approved_delegate_run import (
    resume_approved_delegate_run,
)
from services.agents.runtime.delegation.schemas import DelegateRunResult
from services.agents.runtime.delegation.utils import delegation_precheck_failure
from services.agents.runtime.entity_references.domain import AgentReference, internal_entity_id


async def delegate_to_agent(
    ctx: RunContext[RuntimeDeps],
    agent_id: AgentReference,
    task: Annotated[str, Field(min_length=1, max_length=DELEGATE_TASK_MAX_LENGTH)],
) -> DelegateRunResult:
    """Run a delegated child agent call and return a bounded structured result."""
    normalized_task = task.strip()
    resolved_agent_id = internal_entity_id(agent_id)
    failure = delegation_precheck_failure(ctx, task=normalized_task, subject="Delegate task")
    if failure is not None:
        return DelegateRunResult(
            status="failed",
            agent_id=resolved_agent_id,
            agent_name="Unknown agent",
            error=failure,
        )

    if ctx.tool_call_approved:
        return await resume_approved_delegate_run(
            ctx,
            agent_id=resolved_agent_id,
            authorize_child=lambda session, child_run: _authorize_child(ctx, session, child_run),
        )

    async def resolve_target(session: AsyncSession) -> ChildRunTarget:
        target = await get_visible_delegate_agent(
            session,
            caller=ctx.deps.agent,
            workspace=ctx.deps.workspace,
            target_agent_id=resolved_agent_id,
        )
        return ChildRunTarget(
            agent_id=target.id,
            agent_name=target.name,
            agent_slug=target.slug,
            conversation_title=f"Delegated to {target.name}",
            conversation_metadata={"target_agent_id": str(target.id)},
            run_metadata={"target_agent_id": str(target.id)},
        )

    return await run_child_agent(
        ctx,
        task=normalized_task,
        fallback_agent_id=resolved_agent_id,
        fallback_agent_name="Unknown agent",
        resolve_target=resolve_target,
    )


async def _authorize_child(
    ctx: RunContext[RuntimeDeps], session: AsyncSession, child_run: AgentRun
) -> str:
    target = await get_visible_delegate_agent(
        session,
        caller=ctx.deps.agent,
        workspace=ctx.deps.workspace,
        target_agent_id=child_run.agent_id,
    )
    return target.name
