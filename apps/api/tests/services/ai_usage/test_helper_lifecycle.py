"""Shared helper lifecycle tests."""

from uuid import uuid4

import pytest
from pydantic_ai.usage import RunUsage

from services.ai_usage.domain import AIUsageEventData
from services.ai_usage.run_metered_helper import run_metered_helper

pytestmark = pytest.mark.asyncio


def _event() -> AIUsageEventData:
    return AIUsageEventData(
        workspace_id=uuid4(),
        provider="test",
        model="metered-test",
        purpose="conversation_naming",
    )


async def test_helper_records_one_logical_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[AIUsageEventData] = []

    async def record(event: AIUsageEventData) -> bool:
        recorded.append(event)
        return True

    async def call(usage: RunUsage) -> str:
        usage.requests = 2
        usage.input_tokens = 11
        usage.cache_read_tokens = 3
        usage.cache_write_tokens = 4
        usage.output_tokens = 5
        return "ok"

    monkeypatch.setattr(
        "services.ai_usage.run_metered_helper.record_ai_usage_durable",
        record,
    )
    assert await run_metered_helper(_event(), call) == "ok"
    assert len(recorded) == 1
    assert recorded[0].requests == 2
    assert recorded[0].cache_write_tokens == 4


async def test_helper_records_partial_usage_and_preserves_primary_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[AIUsageEventData] = []

    async def record(event: AIUsageEventData) -> bool:
        recorded.append(event)
        return False

    async def call(usage: RunUsage) -> str:
        usage.requests = 1
        usage.input_tokens = 7
        raise LookupError("primary failure")

    monkeypatch.setattr(
        "services.ai_usage.run_metered_helper.record_ai_usage_durable",
        record,
    )
    with pytest.raises(LookupError, match="primary failure"):
        await run_metered_helper(_event(), call)
    assert recorded[0].input_tokens == 7
