# apps/api/services/agents/runtime/progress_review/openai_decisions.py

"""Reviews progress with one OpenAI Decisions API choice question."""

import json
from typing import cast

from pydantic_ai.exceptions import ContentFilterError
from pydantic_ai.models import check_allow_model_requests
from pydantic_ai.models.decision import ChoiceAnswer, ChoiceQuestion, DecisionRequest
from pydantic_ai.models.openai_decisions import OpenAIDecisionsModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RequestUsage, RunUsage

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
_QUESTION = ChoiceQuestion(criteria=dict(VERDICT_DESCRIPTIONS), instructions=REVIEWER_INSTRUCTIONS)
REFUSED_REASON = "The progress reviewer declined to judge this run."
LOW_CONFIDENCE_REASON = "The progress reviewer wasn't sure enough to let the run carry on."


async def decide_with_openai(
    deps: RuntimeDeps, digest: str, model_spec: ResolvedModel
) -> ProgressReview:
    """Asks Decisions to pick a verdict. It returns no text, so the reason is the choice's description."""
    provider = OpenAIProvider(
        base_url=settings.OPENAI_BASE_URL,
        api_key=provider_api_key(PROVIDER_OPENAI),
        http_client=retrying_http_client(),
    )
    provider.client.max_retries = 0
    model = OpenAIDecisionsModel(model_spec.transport_model, provider=provider)

    async def call(usage: RunUsage) -> ChoiceAnswer | None:
        # decide() skips the guard that Agent runs apply.
        check_allow_model_requests()
        usage.requests = 1
        try:
            response = await model.decide(
                DecisionRequest(state=digest, questions={_QUESTION_NAME: _QUESTION}), {}
            )
        except ContentFilterError as error:
            # A refusal is still billed; its usage is only in the error body.
            usage.incr(_usage_from_body(error.body, model.base_url))
            return None
        usage.incr(response.usage)
        # decide() rejects an answer that doesn't match its choice question.
        return cast(ChoiceAnswer, response.answers[_QUESTION_NAME])

    answer = await run_metered_helper(
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
    if answer is None:
        return ask_person(REFUSED_REASON)
    if answer.confidence < settings.AGENT_RUN_PROGRESS_REVIEW_MIN_CONFIDENCE:
        return ask_person(LOW_CONFIDENCE_REASON)
    return ProgressReview(verdict=answer.choice, reason=VERDICT_DESCRIPTIONS[answer.choice])


def _usage_from_body(body: str | None, base_url: str) -> RequestUsage:
    if not body:
        return RequestUsage()
    return RequestUsage.extract(
        json.loads(body),
        provider="openai-decisions",
        provider_url=base_url,
        provider_fallback="openai",
        api_flavor="responses",
    )
