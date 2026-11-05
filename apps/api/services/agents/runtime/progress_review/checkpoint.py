# apps/api/services/agents/runtime/progress_review/checkpoint.py

"""Reviews progress before a request that would cross the family step limit."""

import asyncio
import logging

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import AgentNode, Hooks, NodeResult
from pydantic_ai.usage import RunUsage

from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.progress_review import review
from services.agents.runtime.progress_review.grant import RequestGrant
from services.agents.runtime.progress_review.verdict import STEER_TEXT, ProgressReview, ask_person
from services.agents.runtime.usage_limits import RuntimeUsageLimits

logger = logging.getLogger(__name__)

GRANTS_USED_REASON = "The run used every automatic extension it is allowed."
REVIEW_UNAVAILABLE_REASON = "The progress review was unavailable."


def install_progress_review_checkpoint(hooks: Hooks) -> None:
    @hooks.on.after_node_run
    async def review_at_step_limit(
        ctx: RunContext[RuntimeDeps], *, node: AgentNode, result: NodeResult
    ) -> NodeResult:
        if Agent.is_model_request_node(result):
            await review_if_due(ctx)
        return result


async def review_if_due(ctx: RunContext[RuntimeDeps]) -> None:
    """Grants more steps, steers, or leaves the next request to trip for a person."""
    limits = ctx.usage_limits
    if not isinstance(limits, RuntimeUsageLimits) or limits.grant is None:
        return
    grant = limits.grant
    if not _due(limits, ctx.usage):
        return
    async with grant.lock:
        # A specialist's review may already have raised the ceiling.
        if not _due(limits, ctx.usage):
            return
        decision = await _decide(ctx, grant)
        grant.record(decision, requests=ctx.usage.requests, steps=limits.family_step_size or 0)
        if grant.persist is not None:
            await grant.persist()
    steer_text = STEER_TEXT.get(decision.verdict)
    if steer_text is not None:
        ctx.enqueue(steer_text, priority="asap")


def _due(limits: RuntimeUsageLimits, usage: RunUsage) -> bool:
    ceiling = limits.family_request_ceiling
    return (
        ceiling is not None
        and usage.requests >= ceiling
        and not limits.hard_request_limit_reached(usage)
    )


async def _decide(ctx: RunContext[RuntimeDeps], grant: RequestGrant) -> ProgressReview:
    if grant.grants_used >= settings.AGENT_RUN_PROGRESS_REVIEW_MAX_GRANTS:
        return ask_person(GRANTS_USED_REASON)
    try:
        async with asyncio.timeout(settings.AGENT_RUN_PROGRESS_REVIEW_TIMEOUT_SECONDS):
            return await review.review_progress(ctx)
    except Exception:
        logger.warning(
            "Progress review failed; asking a person",
            exc_info=True,
            extra={"agent_run_id": str(ctx.deps.run.id)},
        )
        return ask_person(REVIEW_UNAVAILABLE_REASON)
