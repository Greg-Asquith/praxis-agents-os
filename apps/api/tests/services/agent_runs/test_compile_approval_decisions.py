# apps/api/tests/services/agent_runs/test_compile_approval_decisions.py

"""Exercises exact consent identities and owner-scoped workflow compilation."""

from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import DeferredToolRequests, ToolApproved
from pydantic_ai.messages import ModelResponse, ToolCallPart

from core.exceptions.general import ConflictError
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.compile_approval_decisions import compile_approval_decisions
from services.agent_runs.schemas import AgentRunResumeDecision, AgentRunResumeRequest
from services.agents.runtime.approval_projection import build_approval_graph
from services.agents.runtime.approval_state import build_suspended_run_metadata
from services.agents.runtime.code_mode.approval import build_code_mode_approval_metadata
from services.agents.runtime.code_mode.state import build_code_mode_state_metadata
from services.agents.runtime.dispatch import digest_args
from tests.support.approvals import approval_submission


def saved_run(parent=None, *, workflow=False, legacy=False):
    run = AgentRun(
        id=uuid4(),
        conversation_id=uuid4(),
        agent_id=uuid4(),
        workspace_id=parent.workspace_id if parent else uuid4(),
        user_id=parent.user_id if parent else uuid4(),
        parent_run_id=parent.id if parent else None,
        delegation_depth=1 if parent else 0,
        status="awaiting_approval",
        deleted=False,
    )
    nested = ToolCallPart("update", {"value": 1}, "same")
    call = (
        ToolCallPart("run_workflow", {"code": "await update(value=1)"}, "outer")
        if workflow
        else nested
    )
    metadata = (
        {
            "outer": build_code_mode_approval_metadata(
                outer_tool_call_id="outer", nested_call=nested, reason=None
            )
        }
        if workflow
        else {}
    )
    suspend(run, [call], metadata, legacy=legacy)
    if workflow:
        run.metadata_json = build_code_mode_state_metadata(
            run=run,
            outer_tool_call_id="outer",
            nested_call_id="same",
            code="await update(value=1)",
            reason=None,
            snapshot=b"snapshot",
            executed_call_count=0,
            elapsed_seconds=0,
            executed_effects=[],
            nested_trace=[
                {
                    "tool_call_id": "same",
                    "parent_tool_call_id": "outer",
                    "tool_name": "update",
                    "status": "pending",
                    "order": 1,
                    "summary": "Update",
                    "args_sha256": digest_args({"value": 1})[0],
                }
            ],
            snapshot_max_bytes=1024,
            state_max_bytes=1024 * 1024,
        )
    return run


def suspend(run, calls, metadata, *, legacy=False):
    run.metadata_json = build_suspended_run_metadata(
        run=run,
        conversation=Conversation(id=run.conversation_id),
        message_history=[ModelResponse(parts=calls)],
        deferred_tool_requests=DeferredToolRequests(approvals=calls, metadata=metadata),
    )
    if legacy:
        run.metadata_json["approval_state"].pop("approval_batch_id")


def family(*, workflow=False, legacy=False):
    root = saved_run(legacy=legacy)
    children = [saved_run(root, workflow=workflow, legacy=legacy) for _ in range(2)]
    calls = [
        ToolCallPart("delegate_to_agent", {"task": "Update"}, f"delegate-{index}")
        for index in range(2)
    ]
    metadata = {
        call.tool_call_id: {
            "kind": "delegated_child_run",
            "child_run_id": str(child.id),
            "child_agent_id": str(child.agent_id),
            "child_conversation_id": str(child.conversation_id),
        }
        for call, child in zip(calls, children, strict=True)
    }
    suspend(root, calls, metadata, legacy=legacy)
    return root, {run.id: run for run in [root, *children]}


async def compile_for(root, runs, payload):
    return await compile_approval_decisions(
        AsyncMock(),
        actor=User(id=root.user_id),
        workspace=Workspace(id=root.workspace_id),
        membership=WorkspaceMembership(user_id=root.user_id, workspace_id=root.workspace_id),
        graph=build_approval_graph(root, runs),
        runs=runs,
        payload=payload,
    )


@pytest.fixture
def canonicalizer(monkeypatch):
    mock = AsyncMock(side_effect=lambda *args, **kwargs: kwargs["override_args"])
    monkeypatch.setattr(
        "services.agent_runs.compile_approval_decisions.validate_and_canonicalize_override_args",
        mock,
    )
    return mock


@pytest.mark.asyncio
@pytest.mark.parametrize("workflow", [False, True])
async def test_sibling_native_ids_compile_in_each_owner(workflow, canonicalizer):
    from services.agents.runtime.approval_projection import project_approval_graph

    root, runs = family(workflow=workflow)
    projection = project_approval_graph(build_approval_graph(root, runs))
    payload = AgentRunResumeRequest(
        approval_revision=projection.approval_revision,
        decisions=[
            AgentRunResumeDecision(
                tool_call_id=item.tool_call_id,
                approval_id=item.approval_id,
                decision="approved" if index == 0 else "denied",
                override_args={"value": 9} if index == 0 else None,
                message="Skip this" if index else None,
            )
            for index, item in enumerate(projection.approvals)
        ],
    )
    before = {key: deepcopy(run.metadata_json) for key, run in runs.items()}
    result = await compile_for(root, runs, payload)
    assert canonicalizer.await_args.kwargs["run"].id == projection.approvals[0].owner_run_id
    assert canonicalizer.await_args.kwargs["tool_call"].args_as_dict() == {"value": 1}
    first = result.metadata["delegate-0"]["child_deferred_tool_results"]
    second = result.metadata["delegate-1"]["child_deferred_tool_results"]
    if workflow:
        decision = first["metadata"]["outer"]["code_mode_decision"]
        assert decision["effective_args"] == {"value": 9}
        assert decision["args_sha256"] == digest_args({"value": 9})[0]
        assert second["metadata"]["outer"]["code_mode_decision"]["reason"] == "Skip this"
    else:
        assert first["approvals"]["same"]["override_args"] == {"value": 9}
        assert second["metadata"]["same"]["reason"] == "Skip this"
    assert {key: run.metadata_json for key, run in runs.items()} == before


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["stale", "missing", "forged", "native", "duplicate", "legacy"])
async def test_invalid_consent_never_validates_arguments(fault, canonicalizer):
    root = saved_run()
    runs = {root.id: root}
    graph = build_approval_graph(root, runs)
    payload = approval_submission(
        graph, [AgentRunResumeDecision(tool_call_id="same", decision="approved")]
    )
    if fault == "stale":
        payload.approval_revision = "a" * 64
    elif fault == "missing":
        payload.decisions = []
    elif fault == "forged":
        payload.decisions[0].approval_id = uuid4()
    elif fault == "native":
        payload.decisions[0].tool_call_id = "outer"
    elif fault == "duplicate":
        payload.decisions *= 2
    else:
        payload.approval_revision = None
        payload.decisions[0].approval_id = None
    with pytest.raises(ConflictError):
        await compile_for(root, runs, payload)
    canonicalizer.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_unique_direct_history_only(canonicalizer):
    root = saved_run(legacy=True)
    payload = AgentRunResumeRequest(
        decisions=[AgentRunResumeDecision(tool_call_id="same", decision="approved")]
    )
    assert isinstance(
        (await compile_for(root, {root.id: root}, payload)).approvals["same"], ToolApproved
    )
    root.metadata_json["approval_state"]["message_history"][0]["parts"][0]["args"] = {"value": 2}
    with pytest.raises(ConflictError):
        await compile_for(root, {root.id: root}, payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("workflow", [False, True])
async def test_legacy_collisions_and_workflows_require_refresh(workflow, canonicalizer):
    root, runs = family(workflow=workflow, legacy=True)
    payload = AgentRunResumeRequest(
        decisions=[AgentRunResumeDecision(tool_call_id="same", decision="approved")] * 2
    )
    with pytest.raises(ConflictError):
        await compile_for(root, runs, payload)
    canonicalizer.assert_not_awaited()


@pytest.mark.asyncio
async def test_aggregate_result_bound_rejects_expanded_workflow_metadata(canonicalizer):
    root = saved_run(workflow=True)
    graph = build_approval_graph(root, {root.id: root})
    payload = approval_submission(
        graph, [AgentRunResumeDecision(tool_call_id="same", decision="approved")]
    )
    canonicalizer.side_effect = None
    canonicalizer.return_value = {"value": "x" * (4 * 1024 * 1024)}
    with pytest.raises(ConflictError, match="size limit"):
        await compile_for(root, {root.id: root}, payload)
    assert root.status == "awaiting_approval"


def test_repeat_request_digest_handles_mixed_optional_identities():
    from services.agent_runs.continuation_state import resume_request_digest

    decisions = [
        AgentRunResumeDecision(tool_call_id="first", decision="approved", approval_id=uuid4()),
        AgentRunResumeDecision(tool_call_id="second", decision="denied"),
    ]
    assert resume_request_digest(
        AgentRunResumeRequest(decisions=decisions)
    ) == resume_request_digest(AgentRunResumeRequest(decisions=list(reversed(decisions))))
