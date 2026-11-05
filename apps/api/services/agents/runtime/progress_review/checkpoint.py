# apps/api/services/agents/runtime/progress_review/checkpoint.py

"""Reviews progress before a request that would cross the family step limit."""

import asyncio
import logging

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import AgentNode, Hooks, NodeResult
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.usage import RunUsage

from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.progress_review import review
from services.agents.runtime.progress_review.digest import (
    ProgressDigest,
    RunView,
    build_progress_digest,
)
from services.agents.runtime.progress_review.grant import RequestGrant
from services.agents.runtime.progress_review.verdict import (
    STEER_METADATA_KEY,
    ProgressReview,
    ask_person,
    steer_message,
)
from services.agents.runtime.stream_protocol import ProgressReviewEvent
from services.agents.runtime.usage_limits import RuntimeUsageLimits

logger = logging.getLogger(__name__)

REVIEW_UNAVAILABLE_REASON = "The progress review was unavailable."


def install_progress_review_checkpoint(hooks: Hooks, *, root_grant: RequestGrant | None) -> None:
    """Installs the review hook; only the root run passes its grant."""

    @hooks.on.after_node_run
    async def review_at_step_limit(
        ctx: RunContext[RuntimeDeps], *, node: AgentNode, result: NodeResult
    ) -> NodeResult:
        if root_grant is not None:
            root_grant.root_context = ctx
        if Agent.is_model_request_node(result):
            await review_if_due(ctx)
        return result


async def review_if_due(ctx: RunContext[RuntimeDeps]) -> None:
    """Grants more steps, steers, or leaves the next request to trip for a person."""
    limits = ctx.usage_limits
    if not isinstance(limits, RuntimeUsageLimits) or limits.grant is None:
        return
    grant = limits.grant
    if not grant.enabled or not _due(limits, ctx.usage):
        return
    async with grant.lock:
        # A specialist's review may already have raised the ceiling; at the cap the request trips.
        if not _due(limits, ctx.usage) or grant.limit_reached:
            return
        decision, digest = await _decide(ctx, limits, grant)
        granted = grant.record(
            decision, requests=ctx.usage.requests, steps=limits.family_step_size or 0
        )
        steer_text = steer_message(decision, digest.signal if digest else None)
        review_id = (
            await grant.persist(ctx.deps, granted, steer_text)
            if grant.persist is not None
            else None
        )
    if steer_text is not None:
        ctx.enqueue(
            ModelRequest(parts=[UserPromptPart(steer_text)], metadata={STEER_METADATA_KEY: True}),
            priority="asap",
        )
    if review_id is None:
        return
    await ctx.deps.sink.emit(
        ProgressReviewEvent(
            review_id=review_id,
            verdict=decision.verdict,
            reason=decision.reason,
            steer_text=steer_text,
            review_number=len(grant.reviews),
        )
    )


def _due(limits: RuntimeUsageLimits, usage: RunUsage) -> bool:
    ceiling = limits.family_request_ceiling
    return (
        ceiling is not None
        and usage.requests >= ceiling
        and not limits.hard_request_limit_reached(usage)
    )


async def _decide(
    ctx: RunContext[RuntimeDeps], limits: RuntimeUsageLimits, grant: RequestGrant
) -> tuple[ProgressReview, ProgressDigest | None]:
    try:
        digest = _digest(ctx, limits, grant)
        async with asyncio.timeout(settings.AGENT_RUN_PROGRESS_REVIEW_TIMEOUT_SECONDS):
            return await review.review_progress(ctx.deps, digest), digest
    except Exception:
        logger.warning(
            "Progress review failed; asking a person",
            exc_info=True,
            extra={"agent_run_id": str(ctx.deps.run.id)},
        )
        return ask_person(REVIEW_UNAVAILABLE_REASON), None


def _digest(
    ctx: RunContext[RuntimeDeps], limits: RuntimeUsageLimits, grant: RequestGrant
) -> ProgressDigest:
    root_ctx = grant.root_context
    is_specialist = root_ctx is not None and root_ctx.deps.run.id != ctx.deps.run.id
    return build_progress_digest(
        RunView.from_deps(ctx.deps, ctx.messages),
        root=RunView.from_deps(root_ctx.deps, root_ctx.messages) if is_specialist else None,
        requests=ctx.usage.requests,
        step_limit=limits.family_step_size or 0,
        reviews_used=len(grant.reviews),
    )
