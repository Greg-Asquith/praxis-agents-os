# apps/api/tests/scenarios/test_history_trimming.py

"""Cache-stable history behavior through consecutive runtime turns."""

import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from tests.support.scenario import (
    build_scenario_agent,
    next_scenario_run,
    run_scenario,
    scripted_model,
)


async def test_consecutive_turns_keep_a_stable_trim_watermark(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_HISTORY_MAX_TURNS", 6)
    monkeypatch.setattr(settings, "AGENT_HISTORY_KEEP_TURNS", 2)
    context = await build_scenario_agent(db_session_factory)
    requests_by_turn = []

    for index in range(9):
        if index:
            context = await next_scenario_run(db_session_factory, context)
        seen = []
        result = await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(turns=[f"reply {index}"], seen_requests=seen),
            prompt=f"turn {index}",
        )
        assert result.run.status == "completed"
        requests_by_turn.append(seen[0][0])

    penultimate = _boundary_texts(requests_by_turn[-2])
    final = _boundary_texts(requests_by_turn[-1])
    assert penultimate[0] == final[0] == "turn 4"
    assert penultimate[-1] == "turn 7"
    assert final[-1] == "turn 8"


def _boundary_texts(messages):
    return [
        part.content
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart) and isinstance(part.content, str)
    ]
