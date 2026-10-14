# apps/api/services/agents/runtime/tools/native/run_native_helper.py

"""Runs one native helper agent turn with step limits and a metered usage record."""

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.usage import RunUsage, UsageLimits

from services.agents.models.domain import ResolvedModel
from services.agents.runtime.context import RuntimeDeps
from services.ai_usage.domain import AIUsageEventData
from services.ai_usage.run_metered_helper import run_metered_helper


async def run_native_helper[T](
    deps: RuntimeDeps,
    helper: PydanticAgent[None, T],
    prompt: str,
    *,
    model_spec: ResolvedModel,
    purpose: str,
    details: dict[str, object] | None = None,
) -> AgentRunResult[T]:
    """Runs the helper for the calling agent and records one usage row."""

    async def call(usage: RunUsage) -> AgentRunResult[T]:
        return await helper.run(
            prompt,
            usage_limits=UsageLimits(request_limit=model_spec.max_steps),
            usage=usage,
        )

    return await run_metered_helper(
        AIUsageEventData(
            workspace_id=deps.workspace.id,
            provider=model_spec.provider,
            model=model_spec.model,
            purpose=purpose,
            agent_id=deps.agent.id,
            user_id=deps.user.id,
            run_id=deps.run.id,
            conversation_id=deps.conversation.id,
            details=details,
        ),
        call,
    )
