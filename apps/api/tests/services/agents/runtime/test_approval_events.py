"""Approval-only presentation metadata contracts."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ToolCallPart

from services.agent_runs.schemas import AgentRunApprovalStateResponse, PendingToolApprovalRead
from services.agents.runtime.approval_events import (
    add_approval_display_args,
    approval_events_for_projection,
)
from services.agents.runtime.code_mode.approval import build_code_mode_approval_metadata
from services.agents.runtime.staged_tool_content import (
    tool_args_for_display,
    tool_replay_args_for_editing,
)


def test_projected_events_preserve_leaf_identity_and_server_proposal() -> None:
    root_id = uuid4()
    approvals = [
        PendingToolApprovalRead(
            approval_id=uuid4(),
            owner_run_id=uuid4(),
            root_run_id=root_id,
            tool_call_id="shared-native-call",
            parent_tool_call_id="shared-outer-call",
            name="external_write",
            args={"amount": "12.50", "_currency_code": "GBP"},
            replay_args={"amount": "12.50"},
            derived_from_untrusted=True,
            taint_sources=[{"source_kind": "tool", "source_ref": "source"}],
        )
        for _ in range(2)
    ]
    projection = AgentRunApprovalStateResponse(
        run_id=root_id,
        conversation_id=uuid4(),
        approval_revision="a" * 64,
        approvals=approvals,
    )

    events = approval_events_for_projection(projection)

    assert events[0].approval_id != events[1].approval_id
    assert events[0].owner_run_id != events[1].owner_run_id
    for event, approval in zip(events, approvals, strict=True):
        assert event.serialize_payload() == {
            **approval.model_dump(mode="json", exclude_none=True),
            "approval_revision": projection.approval_revision,
        }
        assert event.tool_call_id == "shared-native-call"
        assert event.parent_tool_call_id == "shared-outer-call"


@pytest.mark.parametrize("nested", [False, True])
async def test_adds_display_args_without_changing_replay_args(monkeypatch, nested: bool) -> None:
    call = ToolCallPart(
        tool_name="external_write",
        tool_call_id="nested-call" if nested else "direct-call",
        args={"amount": "12.50"},
    )
    outer = (
        ToolCallPart(tool_name="run_workflow", tool_call_id="outer-call", args={})
        if nested
        else call
    )
    metadata = (
        {
            outer.tool_call_id: build_code_mode_approval_metadata(
                outer_tool_call_id=outer.tool_call_id,
                nested_call=call,
                reason="Review the write.",
            )
        }
        if nested
        else {}
    )
    definition = SimpleNamespace(
        approval_display_args=lambda _deps, args: {**args, "_currency_code": "GBP"}
    )
    monkeypatch.setattr(
        "services.agents.runtime.approval_events.resolve_runtime_tool_definition",
        lambda _name, _definitions: definition,
    )

    enriched = await add_approval_display_args(
        SimpleNamespace(workspace_tool_definitions=()),
        DeferredToolRequests(approvals=[outer], metadata=metadata),
    )

    approval_metadata = enriched.metadata[outer.tool_call_id]
    assert tool_args_for_display(
        tool_name=call.tool_name,
        args=call.args,
        metadata=approval_metadata,
    ) == {"amount": "12.50", "_currency_code": "GBP"}
    assert tool_replay_args_for_editing(
        tool_name=call.tool_name,
        args=call.args,
        metadata=approval_metadata,
    ) == {"amount": "12.50"}


async def test_display_arg_failure_persists_blocked_approval_without_changing_replay_args(
    monkeypatch,
) -> None:
    call = ToolCallPart(
        tool_name="external_write",
        tool_call_id="direct-call",
        args={"amount": "12.50"},
    )

    def fail_projection(_deps, _args):
        raise RuntimeError("missing display metadata")

    monkeypatch.setattr(
        "services.agents.runtime.approval_events.resolve_runtime_tool_definition",
        lambda _name, _definitions: SimpleNamespace(approval_display_args=fail_projection),
    )

    enriched = await add_approval_display_args(
        SimpleNamespace(workspace_tool_definitions=()),
        DeferredToolRequests(approvals=[call]),
    )

    metadata = enriched.metadata[call.tool_call_id]
    assert tool_args_for_display(
        tool_name=call.tool_name,
        args=call.args,
        metadata=metadata,
    ) == {
        "amount": "12.50",
        "_approval_display_error": (
            "Approval details are unavailable. Ask the agent to prepare this action again."
        ),
    }
    assert tool_replay_args_for_editing(
        tool_name=call.tool_name,
        args=call.args,
        metadata=metadata,
    ) == {"amount": "12.50"}
