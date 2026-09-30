# apps/api/services/agents/runtime/subagents/run_subagent.py

"""Hand one token-heavy task to a throwaway sub-agent and return only its result."""

from typing import Annotated

from pydantic import Field
from pydantic_ai import RunContext
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.agent import Agent
from models.agent_run import AgentRun
from services.agents.models.domain import ModelType
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.delegation.child_run import ChildRunTarget, run_child_agent
from services.agents.runtime.delegation.constants import DELEGATE_TASK_MAX_LENGTH
from services.agents.runtime.delegation.resume_approved_delegate_run import (
    resume_approved_delegate_run,
)
from services.agents.runtime.delegation.schemas import DelegateRunResult
from services.agents.runtime.delegation.utils import (
    delegation_precheck_failure,
    load_caller_agent,
)
from services.agents.runtime.subagents.constants import (
    SUBAGENT_INSTRUCTIONS_MAX_LENGTH,
    SUBAGENT_METADATA_KEY,
    SUBAGENT_NOT_ALLOWED_ERROR_MESSAGE,
    SUBAGENT_ROLE_MAX_LENGTH,
)
from services.agents.runtime.subagents.resolve_subagent_model import (
    resolve_subagent_model,
    within_parent_model,
)
from services.agents.runtime.subagents.spec import SubagentSpec, subagent_spec_from_metadata


async def run_subagent(
    ctx: RunContext[RuntimeDeps],
    role: Annotated[str, Field(min_length=1, max_length=SUBAGENT_ROLE_MAX_LENGTH)],
    instructions: Annotated[str, Field(min_length=1, max_length=SUBAGENT_INSTRUCTIONS_MAX_LENGTH)],
    task: Annotated[str, Field(min_length=1, max_length=DELEGATE_TASK_MAX_LENGTH)],
    model_tier: ModelType | None = None,
) -> DelegateRunResult:
    """Run a sub-agent with your tools and return its final answer.

    Args:
        role: A short name for the sub-agent, shown to the user, such as "Search term researcher".
        instructions: Who the sub-agent is and how it should work. End by asking for a concise final answer.
        task: The complete task, with every detail the sub-agent needs. It cannot see this conversation.
        model_tier: light, standard, powerful, or max. Omit to use the workspace default model.
    """
    parent = ctx.deps.agent
    normalized_role = " ".join(role.split())
    normalized_task = task.strip()
    failure = delegation_precheck_failure(ctx, task=normalized_task, subject="Sub-agent task")
    if failure is None and not (normalized_role and instructions.strip()):
        failure = "Sub-agent role and instructions must not be blank."
    if failure is not None:
        return DelegateRunResult(
            status="failed", agent_id=parent.id, agent_name=normalized_role, error=failure
        )

    if ctx.tool_call_approved:
        return await resume_approved_delegate_run(
            ctx,
            agent_id=parent.id,
            authorize_child=lambda session, child_run: _authorize_child(ctx, session, child_run),
        )

    async def resolve_target(session: AsyncSession) -> ChildRunTarget:
        caller = await _require_subagents_enabled(ctx, session)
        model_provider, model = resolve_subagent_model(
            caller, workspace=ctx.deps.workspace, model_tier=model_tier
        )
        spec = SubagentSpec(
            role=normalized_role,
            instructions=instructions.strip(),
            model_provider=model_provider,
            model=model,
        )
        return ChildRunTarget(
            agent_id=parent.id,
            agent_name=spec.role,
            agent_slug=parent.slug,
            conversation_title=f"Helper: {spec.role}",
            conversation_metadata={"subagent_role": spec.role},
            run_metadata={SUBAGENT_METADATA_KEY: spec.model_dump(mode="json")},
        )

    return await run_child_agent(
        ctx,
        task=normalized_task,
        fallback_agent_id=parent.id,
        fallback_agent_name=normalized_role,
        resolve_target=resolve_target,
    )


async def _require_subagents_enabled(ctx: RunContext[RuntimeDeps], session: AsyncSession) -> Agent:
    caller = await load_caller_agent(session, caller=ctx.deps.agent, workspace=ctx.deps.workspace)
    if not (caller.is_active and caller.subagents_enabled):
        raise NotFoundError(SUBAGENT_NOT_ALLOWED_ERROR_MESSAGE, resource_type="agent")
    return caller


async def _authorize_child(
    ctx: RunContext[RuntimeDeps], session: AsyncSession, child_run: AgentRun
) -> str:
    spec = subagent_spec_from_metadata(child_run.metadata_json)
    if spec is None or child_run.agent_id != ctx.deps.agent.id:
        raise NotFoundError("Sub-agent run not found", resource_type="agent_run")
    caller = await _require_subagents_enabled(ctx, session)
    # The parent's model may have changed since the pause; never resume above it.
    if not within_parent_model(
        caller, workspace=ctx.deps.workspace, model_provider=spec.model_provider, model=spec.model
    ):
        raise NotFoundError("Sub-agent model is above its parent's", resource_type="agent")
    return spec.role
