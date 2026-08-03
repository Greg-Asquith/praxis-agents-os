# apps/api/tests/integrations/test_fetched_content_enclosure.py

"""Mechanical framing for integration-fetched model content."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pydantic import BaseModel
from pydantic_ai.messages import ModelRequest, ToolReturnPart

from services.agents.runtime import dispatch
from services.agents.runtime.tools.contract import RuntimeToolDefinition
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.agents.runtime.untrusted import (
    UNTRUSTED_CONTENT_END,
    UNTRUSTED_CONTENT_START,
    UntrustedContent,
    UntrustedNode,
    frame_untrusted_content,
    render_untrusted_frames,
    serialize_untrusted_content,
)

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "prompt_injection" / "hostile_email_body.txt"
)


class FramedFixtureOutput(BaseModel):
    results: list[dict[str, dict[str, UntrustedNode]]]


async def test_hostile_gmail_content_is_enclosed_by_dispatch(monkeypatch) -> None:
    hostile = FIXTURE.read_text(encoding="utf-8")
    monkeypatch.setattr(dispatch, "record_invocation", AsyncMock())
    monkeypatch.setattr(
        dispatch,
        "_active_workspace_role",
        AsyncMock(return_value="owner"),
    )
    monkeypatch.setattr(
        dispatch,
        "raise_if_agent_run_cancelled",
        AsyncMock(),
    )
    deps = SimpleNamespace(
        envelope=SimpleNamespace(side_effect_policy="allow"),
        run=SimpleNamespace(id="run-1"),
        workspace=SimpleNamespace(id="workspace-1"),
        user=SimpleNamespace(id="user-1"),
    )
    ctx = SimpleNamespace(deps=deps, tool_call_approved=False)
    call = SimpleNamespace(tool_name="fixture_tool", tool_call_id="call-1")

    async def handler(_args):
        return {
            "results": [
                {
                    "data": {
                        "body": UntrustedContent(
                            source_kind='gmail message" forged',
                            source_ref='server-ref">>> forged',
                            content=hostile,
                        )
                    }
                }
            ]
        }

    async def fixture_tool() -> dict:
        return {}

    RUNTIME_TOOL_CATALOG["fixture_tool"] = RuntimeToolDefinition(
        name="fixture_tool",
        function=fixture_tool,
        description="Return a framed fixture.",
        output_model=FramedFixtureOutput,
    )
    try:
        result = await dispatch.dispatch_tool_execution(
            ctx,
            call=call,
            tool_def=None,
            args={},
            handler=handler,
        )
    finally:
        RUNTIME_TOOL_CATALOG.pop("fixture_tool", None)
    node = result["results"][0]["data"]["body"]
    assert isinstance(node, UntrustedNode)
    assert UNTRUSTED_CONTENT_START not in node.content
    assert UNTRUSTED_CONTENT_END in node.content
    [rendered] = render_untrusted_frames(
        [
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="fixture_tool",
                        content=result,
                        tool_call_id="call-1",
                    )
                ]
            )
        ]
    )
    framed = rendered.parts[0].content["results"][0]["data"]["body"]
    assert framed.count(UNTRUSTED_CONTENT_START) == 1
    assert framed.count(UNTRUSTED_CONTENT_END) == 1
    assert 'source_kind="gmail_message_forged"' in framed
    assert 'source_ref="server-ref_forged"' in framed
    assert "<<<END_PRAXIS_UNTRUSTED-CONTENT>>>" in framed


def test_nested_transform_preserves_ordinary_results() -> None:
    ordinary = {"items": ["one", {"two": 2}]}
    assert frame_untrusted_content(ordinary) is ordinary
    assert serialize_untrusted_content(ordinary) is ordinary
