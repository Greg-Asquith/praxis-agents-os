"""Test tools and persisted approval continuations for runtime scenarios."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from pydantic_ai import RunContext
from pydantic_ai.models import Model
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.resume_run_stream import _build_deferred_tool_results
from services.agent_runs.schemas import AgentRunResumeDecision
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.run_persistence import restored_run_usage
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
)
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG, runtime_tool
from tests.support.scenario import ScenarioContext, ScenarioResult, run_scenario


@dataclass
class ScenarioEffects:
    name: str = field(default_factory=lambda: f"scenario_effect_{uuid4().hex}")
    calls: list[tuple[UUID, str]] = field(default_factory=list)


@contextmanager
def scenario_effects() -> Iterator[ScenarioEffects]:
    """Records real dispatch invocations without contacting an external provider."""
    effects = ScenarioEffects()

    @runtime_tool(
        name=effects.name,
        provider="test",
        description="Record a scenario effect and its owning run.",
        takes_ctx=True,
        effect=TOOL_EFFECT_WRITE,
        effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
        egress=TOOL_EGRESS_EXTERNAL_WRITE,
        configurable=False,
        code_eligible=True,
    )
    async def write(ctx: RunContext[RuntimeDeps], value: str) -> str:
        effects.calls.append((ctx.deps.run.id, value))
        return value

    try:
        yield effects
    finally:
        RUNTIME_TOOL_CATALOG.pop(effects.name, None)


async def resume_scenario(
    session_factory: async_sessionmaker[AsyncSession],
    context: ScenarioContext,
    *,
    model: Model,
    decisions: Sequence[AgentRunResumeDecision],
) -> ScenarioResult:
    """Rehydrates committed state and compiles decisions through the production seam."""
    async with session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        actor = await db.get(User, context.user_id)
        workspace = await db.get(Workspace, context.workspace_id)
        membership = await db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == context.workspace_id,
                WorkspaceMembership.user_id == context.user_id,
            )
        )
        state = load_suspended_run_state(run)
        usage = restored_run_usage(run)
        results = await _build_deferred_tool_results(
            db,
            actor=actor,
            workspace=workspace,
            membership=membership,
            run=run,
            suspended_state=state,
            decisions=list(decisions),
        )
    return await run_scenario(
        session_factory,
        context,
        model=model,
        prompt=None,
        expected_status="awaiting_approval",
        message_history=state.message_history,
        deferred_tool_results=results,
        usage=usage,
    )
