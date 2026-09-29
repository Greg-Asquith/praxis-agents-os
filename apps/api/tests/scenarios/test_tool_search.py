# apps/api/tests/scenarios/test_tool_search.py

"""Deferred tool discovery through the real runtime lifecycle."""

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


@pytest.mark.deferred_tools
async def test_model_searches_for_a_deferred_tool_then_calls_it_through_dispatch(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(db_session_factory, tool_names=["test_add_numbers"])
    seen: list[tuple[list[ModelMessage], AgentInfo]] = []
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall("search_tools", {"queries": ["add numbers"]}, "search-call"),)),
            ToolTurn((ToolCall("test_add_numbers", {"a": 7, "b": 5}, "add-call"),)),
            "The total is 12.",
        ],
        seen_requests=seen,
    )

    result = await run_scenario(db_session_factory, context, model=model)

    first, second = (info.model_request_parameters for _messages, info in seen[:2])
    assert "test_add_numbers" not in first.revealed_tool_names
    assert "test_add_numbers" in second.revealed_tool_names
    assert "search_memory" not in first.revealed_tool_names
    [added] = result.tool_returns("test_add_numbers")
    assert added["content"] == 12
    assert any(
        row.tool_name == "test_add_numbers" and row.status == "success" for row in result.audit_rows
    )
    assert result.run.status == "completed"
