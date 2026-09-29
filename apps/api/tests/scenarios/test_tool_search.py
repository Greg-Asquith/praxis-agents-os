# apps/api/tests/scenarios/test_tool_search.py

"""Deferred tool discovery through the real runtime lifecycle."""

from dataclasses import replace

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.agents.runtime.tools.code_mode import RUN_WORKFLOW_TOOL_NAME
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


@pytest.mark.deferred_tools
async def test_model_discovers_a_deferred_tool_then_calls_it_directly_and_in_a_workflow(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = replace(RUNTIME_TOOL_CATALOG["test_add_numbers"], code_eligible=True)
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, definition.name, definition)
    context = await build_scenario_agent(db_session_factory, tool_names=["test_add_numbers"])
    seen: list[tuple[list[ModelMessage], AgentInfo]] = []
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall("search_tools", {"queries": ["add numbers"]}, "search-call"),)),
            ToolTurn((ToolCall("test_add_numbers", {"a": 7, "b": 5}, "add-call"),)),
            ToolTurn(
                (
                    ToolCall(
                        RUN_WORKFLOW_TOOL_NAME,
                        {
                            "code": (
                                "first = await test_add_numbers(a=12, b=1)\n"
                                "await test_add_numbers(a=first, b=2)"
                            )
                        },
                        "workflow-call",
                    ),
                )
            ),
            "The total is 15.",
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
    [workflow] = result.tool_returns(RUN_WORKFLOW_TOOL_NAME)
    assert workflow["content"] == 15
    assert sorted(
        row.details.get("parent_tool_call_id") is not None
        for row in result.audit_rows
        if row.tool_name == "test_add_numbers" and row.status == "success"
    ) == [False, True, True]
    assert result.run.status == "completed"
