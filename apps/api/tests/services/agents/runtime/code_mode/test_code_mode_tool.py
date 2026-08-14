"""Tests for the catalog-bound `run_workflow` runtime tool."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import ModelRetry, RunContext, ToolReturn
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage

from services.agents.runtime.code_mode.stubs import CodeModeCatalog
from services.agents.runtime.tools import code_mode


def _ctx(*, trigger: str, tool_call_id: str | None = "workflow-call") -> RunContext:
    return RunContext(
        deps=SimpleNamespace(run=SimpleNamespace(trigger=trigger, metadata_json={"kept": True})),
        model=TestModel(),
        usage=RunUsage(),
        tool_call_id=tool_call_id,
        tool_name="run_workflow",
    )


async def test_run_workflow_closes_over_catalog_and_stamps_run_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = CodeModeCatalog.build(())
    expected = ToolReturn(return_value={"done": True})
    execute = AsyncMock(return_value=expected)
    monkeypatch.setattr(code_mode, "execute_code_mode_workflow", execute)
    tool = code_mode.build_run_workflow_tool(catalog)
    ctx = _ctx(trigger="interactive")

    result = await tool.function(ctx, code="{'done': True}", reason="Compose reads")

    assert result is expected
    assert ctx.deps.run.metadata_json == {
        "kept": True,
        "code_mode": {"wrapped_tool_names": []},
    }
    execute.assert_awaited_once_with(
        ctx=ctx,
        wrapped_toolset=catalog.wrapped_toolset,
        outer_tool_call_id="workflow-call",
        code="{'done': True}",
        reason="Compose reads",
    )


@pytest.mark.parametrize("trigger", ["scheduled", "delegated", "event"])
async def test_run_workflow_is_available_to_unattended_principals(trigger: str) -> None:
    tool = code_mode.build_run_workflow_tool(CodeModeCatalog.build(()))

    prepared = await FunctionToolset([tool]).get_tools(_ctx(trigger=trigger))

    assert set(prepared) == {"run_workflow"}


async def test_run_workflow_is_available_to_interactive_principals() -> None:
    tool = code_mode.build_run_workflow_tool(CodeModeCatalog.build(()))

    prepared = await FunctionToolset([tool]).get_tools(_ctx(trigger="interactive"))

    assert set(prepared) == {"run_workflow"}


async def test_run_workflow_requires_outer_call_identity() -> None:
    tool = code_mode.build_run_workflow_tool(CodeModeCatalog.build(()))

    with pytest.raises(ModelRetry, match="missing its runtime identity"):
        await tool.function(_ctx(trigger="interactive", tool_call_id=None), code="1")
