# apps/api/services/agents/runtime/progress_review/review.py

"""Asks the configured reviewer whether a run should carry on past its step limit."""

from pydantic import BaseModel, Field
from pydantic_ai import Agent as PydanticAgent

from services.agents.models import build_model, resolve_progress_review_model
from services.agents.models.domain import PROVIDER_OPENAI, ResolvedModel
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.progress_review.digest import ProgressDigest
from services.agents.runtime.progress_review.verdict import (
    GUIDANCE_MAX_CHARS,
    REASON_MAX_CHARS,
    REVIEWER_INSTRUCTIONS,
    STEER_TEXT,
    VERDICT_DESCRIPTIONS,
    ProgressReview,
    Verdict,
)
from services.agents.runtime.tools.native.run_native_helper import run_native_helper
from services.ai_usage.domain import PURPOSE_RUN_REVIEW

_INSTRUCTIONS = (
    REVIEWER_INSTRUCTIONS
    + "\nVerdicts:\n"
    + "\n".join(f"- {verdict}: {text}" for verdict, text in VERDICT_DESCRIPTIONS.items())
)


class ReviewerVerdict(BaseModel):
    """Structured output requested from Anthropic and Google reviewer models."""

    verdict: Verdict
    reason: str = Field(
        description=f"One or two sentences explaining the verdict, {REASON_MAX_CHARS} characters "
        "at most."
    )
    guidance: str | None = Field(
        default=None,
        description=f"For steer verdicts only: one short, specific hint for the agent, "
        f"{GUIDANCE_MAX_CHARS} characters at most.",
    )


async def review_progress(deps: RuntimeDeps, digest: ProgressDigest) -> ProgressReview:
    """Returns the reviewer's verdict. The checkpoint maps every failure to asking a person."""
    model_spec = resolve_progress_review_model()
    if model_spec.provider == PROVIDER_OPENAI:
        # Loads the OpenAI SDK only when a review uses it.
        from services.agents.runtime.progress_review.openai_decisions import decide_with_openai

        review = await decide_with_openai(deps, digest.text, model_spec)
    else:
        review = await _review_with_structured_output(deps, digest.text, model_spec)
    return review.model_copy(update={"provider": model_spec.provider, "model": model_spec.model})


async def _review_with_structured_output(
    deps: RuntimeDeps, digest: str, model_spec: ResolvedModel
) -> ProgressReview:
    helper = PydanticAgent(
        build_model(model_spec),
        name=f"praxis_progress_reviewer_{model_spec.provider}",
        output_type=ReviewerVerdict,
        instructions=_INSTRUCTIONS,
    )
    result = await run_native_helper(
        deps, helper, digest, model_spec=model_spec, purpose=PURPOSE_RUN_REVIEW
    )
    output = result.output
    return ProgressReview(
        verdict=output.verdict,
        reason=(output.reason.strip() or VERDICT_DESCRIPTIONS[output.verdict])[:REASON_MAX_CHARS],
        guidance=(output.guidance or "")[:GUIDANCE_MAX_CHARS] or None
        if output.verdict in STEER_TEXT
        else None,
    )
