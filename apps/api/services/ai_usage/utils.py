# apps/api/services/ai_usage/utils.py

"""Shared AI usage conversion and persistence mechanics."""

from typing import Any

from pydantic_ai.messages import ModelResponse
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from models.ai_usage_event import AIUsageEvent
from services.ai_usage.domain import AIUsageEventData


def usage_values(usage: Any) -> dict[str, int]:
    """Return the four token classes and request count from Pydantic AI usage."""
    values: dict[str, int] = {}
    for name in (
        "input_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "output_tokens",
        "requests",
    ):
        raw = getattr(usage, name, 0) or 0
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError(f"AI usage {name} must be a non-negative integer")
        values[name] = raw
    return values


def subtract_usage(current: RunUsage, baseline: RunUsage) -> dict[str, int]:
    current_values = usage_values(current)
    baseline_values = usage_values(baseline)
    return {name: max(0, value - baseline_values[name]) for name, value in current_values.items()}


def sum_response_usage(messages: list[object]) -> dict[str, int]:
    total = dict.fromkeys(usage_values(RunUsage()), 0)
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        response_values = usage_values(message.usage)
        response_values["requests"] = 1
        for name, value in response_values.items():
            total[name] += value
    return total


def add_event(db: AsyncSession, event: AIUsageEventData) -> None:
    db.add(
        AIUsageEvent(
            workspace_id=event.workspace_id,
            provider=event.provider,
            model=event.model,
            purpose=event.purpose,
            input_tokens=event.input_tokens,
            cache_read_tokens=event.cache_read_tokens,
            cache_write_tokens=event.cache_write_tokens,
            output_tokens=event.output_tokens,
            requests=event.requests,
            agent_id=event.agent_id,
            user_id=event.user_id,
            run_id=event.run_id,
            conversation_id=event.conversation_id,
            details=event.details,
        )
    )
