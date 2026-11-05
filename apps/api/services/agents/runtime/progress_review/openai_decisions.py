# apps/api/services/agents/runtime/progress_review/openai_decisions.py

"""Reviews progress with one OpenAI Decisions API choice question."""

from openai import AsyncOpenAI
from openai.types import Decision
from pydantic_ai.usage import RunUsage

from core.settings import settings
from services.agents.models.domain import PROVIDER_OPENAI, ResolvedModel
from services.agents.models.utils import provider_api_key, retrying_http_client
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.progress_review.verdict import (
    REVIEWER_INSTRUCTIONS,
    VERDICT_DESCRIPTIONS,
    ProgressReview,
    ask_person,
)
from services.ai_usage.domain import PURPOSE_RUN_REVIEW, AIUsageEventData
from services.ai_usage.run_metered_helper import run_metered_helper

_QUESTION_NAME = "verdict"
REFUSED_REASON = "The progress reviewer declined to judge this run."
UNEXPECTED_ANSWER_REASON = "The progress reviewer returned an answer Praxis couldn't use."
LOW_CONFIDENCE_REASON = "The progress reviewer wasn't sure enough to let the run carry on."


async def decide_with_openai(
    deps: RuntimeDeps, digest: str, model_spec: ResolvedModel
) -> ProgressReview:
    """Asks Decisions to pick a verdict. It returns no text, so the reason is the choice's description."""
    client = AsyncOpenAI(
        api_key=provider_api_key(PROVIDER_OPENAI),
        base_url=settings.OPENAI_BASE_URL,
        http_client=retrying_http_client(),
        max_retries=0,
    )

    async def call(usage: RunUsage) -> Decision:
        usage.requests = 1
        decision = await client.decisions.create(
            model=model_spec.transport_model,
            input=digest,
            questions=[
                {
                    "type": "choice",
                    "name": _QUESTION_NAME,
                    "instructions": REVIEWER_INSTRUCTIONS,
                    "choices": [
                        {"value": verdict, "description": description}
                        for verdict, description in VERDICT_DESCRIPTIONS.items()
                    ],
                }
            ],
        )
        usage.input_tokens = decision.usage.input_tokens
        usage.cache_read_tokens = decision.usage.input_tokens_details.cached_tokens
        usage.cache_write_tokens = decision.usage.input_tokens_details.cache_write_tokens
        usage.output_tokens = decision.usage.output_tokens
        return decision

    decision = await run_metered_helper(
        AIUsageEventData(
            workspace_id=deps.workspace.id,
            provider=model_spec.provider,
            model=model_spec.model,
            purpose=PURPOSE_RUN_REVIEW,
            agent_id=deps.agent.id,
            user_id=deps.user.id,
            run_id=deps.run.id,
            conversation_id=deps.conversation.id,
        ),
        call,
    )
    return review_from_decision(decision)


def review_from_decision(decision: Decision) -> ProgressReview:
    answer = next((item for item in decision.answers if item.name == _QUESTION_NAME), None)
    if answer is None or answer.type == "refusal":
        return ask_person(REFUSED_REASON)
    if answer.type != "choice" or answer.choice not in VERDICT_DESCRIPTIONS:
        return ask_person(UNEXPECTED_ANSWER_REASON)
    if answer.confidence < settings.AGENT_RUN_PROGRESS_REVIEW_MIN_CONFIDENCE:
        return ask_person(LOW_CONFIDENCE_REASON)
    return ProgressReview(verdict=answer.choice, reason=VERDICT_DESCRIPTIONS[answer.choice])
