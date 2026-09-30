"""Tests for the per-run `run_code` runtime tool."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import ModelRetry, RunContext, ToolReturn
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from services.agents.runtime.tools import code_mode
from services.agents.runtime.tools.contract import RuntimeToolDefinition


def _ctx(*, trigger: str, tool_call_id: str | None = "workflow-call") -> RunContext:
    return RunContext(
        deps=SimpleNamespace(run=SimpleNamespace(trigger=trigger, metadata_json={"kept": True})),
        model=TestModel(),
        usage=RunUsage(),
        tool_call_id=tool_call_id,
        tool_name="run_code",
    )


async def test_run_code_exposes_deferred_tools_to_nested_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = RuntimeToolDefinition(
        name="deferred_read",
        function=lambda query: query,
        description="Read after tool search.",
        code_eligible=True,
    )
    expected = ToolReturn(return_value={"done": True})
    execute = AsyncMock(return_value=expected)
    monkeypatch.setattr(code_mode, "execute_code_mode_workflow", execute)
    tool = code_mode.build_run_code_tool(((definition, "approval"),))
    ctx = _ctx(trigger="interactive")

    result = await tool.function(ctx, code="{'done': True}", reason="Compose reads")

    assert result is expected
    nested = execute.await_args.kwargs["wrapped_toolset"].tools["deferred_read"]
    assert nested.defer_loading is False
    assert nested.requires_approval is True


async def test_run_code_requires_outer_call_identity() -> None:
    tool = code_mode.build_run_code_tool(())

    with pytest.raises(ModelRetry, match="missing its runtime identity"):
        await tool.function(_ctx(trigger="interactive", tool_call_id=None), code="1")
