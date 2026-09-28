"""Approval identity and projection cases using durable state serializers."""

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ToolCallPart

from core.exceptions.general import ConflictError
from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agents.runtime.approval_identity import proposal_digest
from services.agents.runtime.approval_projection import (
    DelegatedApprovalNode,
    build_approval_graph,
    project_approval_graph,
)
from services.agents.runtime.approval_state import (
    build_suspended_run_metadata,
    load_suspended_run_state,
)
from services.agents.runtime.code_mode.approval import build_code_mode_approval_metadata
from services.agents.runtime.code_mode.state import build_code_mode_state_metadata


def saved_run(*, parent=None, calls=None, metadata=None):
    run = AgentRun(
        id=uuid4(),
        conversation_id=uuid4(),
        agent_id=uuid4(),
        workspace_id=parent.workspace_id if parent else uuid4(),
        user_id=parent.user_id if parent else uuid4(),
        parent_run_id=parent.id if parent else None,
        delegation_depth=1 if parent else 0,
        status="awaiting_approval",
        trigger="delegated" if parent else "interactive",
        deleted=False,
    )
    suspend(run, calls or [ToolCallPart("update", {"value": 1}, "same-id")], metadata)
    return run


def suspend(run, calls, metadata=None):
    run.metadata_json = build_suspended_run_metadata(
        run=run,
        conversation=Conversation(id=run.conversation_id),
        message_history=[],
        deferred_tool_requests=DeferredToolRequests(approvals=calls, metadata=metadata or {}),
    )


def delegate(root, children):
    suspend(
        root,
        [
            ToolCallPart("delegate_to_agent", {"task": "Update"}, f"delegate-{index}")
            for index, _ in enumerate(children)
        ],
        {
            f"delegate-{index}": {
                "kind": "delegated_child_run",
                "child_run_id": str(child.id),
                "child_agent_id": str(child.agent_id),
                "child_conversation_id": str(child.conversation_id),
                "child_agent_name": f"Specialist {index}",
            }
            for index, child in enumerate(children)
        },
    )


def workflow(run):
    nested = ToolCallPart("update", {"value": 2}, "same-id")
    metadata = build_code_mode_approval_metadata(
        outer_tool_call_id="workflow",
        nested_call=nested,
        reason="Review update",
        derived_from_untrusted=True,
        taint_sources=[{"source_kind": "integration", "source_ref": "row"}],
    )
    suspend(
        run,
        [ToolCallPart("run_workflow", {"code": "await update(value=2)"}, "workflow")],
        {"workflow": metadata},
    )
    run.metadata_json = build_code_mode_state_metadata(
        run=run,
        outer_tool_call_id="workflow",
        nested_call_id="same-id",
        code="await update(value=2)",
        reason="Review update",
        snapshot=b"private-snapshot",
        executed_call_count=1,
        elapsed_seconds=1,
        executed_effects=[],
        nested_trace=[
            {
                "tool_call_id": "done",
                "parent_tool_call_id": "workflow",
                "args_sha256": "abc",
                "tool_name": "update",
                "status": "denied",
                "summary": "Declined",
                "order": 1,
                "excerpt": "Not performed",
                "presentation_result": {"status": "denied"},
            },
            {
                "tool_call_id": "same-id",
                "parent_tool_call_id": "workflow",
                "tool_name": "update",
                "args_sha256": proposal_digest({"value": 2}),
                "summary": "Update",
                "status": "pending",
                "order": 2,
            },
        ],
        snapshot_max_bytes=1024,
        state_max_bytes=1024 * 1024,
    )


def test_sibling_and_root_native_collisions_remain_distinct():
    root = saved_run()
    children = [saved_run(parent=root), saved_run(parent=root)]
    delegate(root, children)
    state = load_suspended_run_state(root)
    suspend(
        root,
        [*state.deferred_tool_requests.approvals, ToolCallPart("update", {"value": 1}, "same-id")],
        state.deferred_tool_requests.metadata,
    )
    response = project_approval_graph(
        build_approval_graph(root, {child.id: child for child in children})
    )
    assert len({item.approval_id for item in response.approvals}) == 3
    assert {item.tool_call_id for item in response.approvals} == {"same-id"}
    assert {item.owner_run_id for item in response.approvals} == {
        root.id,
        *(child.id for child in children),
    }


@pytest.mark.parametrize(
    "fields",
    [{"approval_batch_id": None}, {"approval_batch_id": "bad"}, {"approval_revision": "bad"}],
)
def test_invalid_identity_metadata_fails_closed(fields):
    root = saved_run()
    root.metadata_json["approval_state"].update(fields)
    with pytest.raises(ConflictError):
        build_approval_graph(root, {})


@pytest.mark.parametrize("fault", ["snapshot", "nested", "outer", "missing_state"])
def test_workflow_corruption_fails_closed(fault):
    root = saved_run()
    workflow(root)
    if fault == "snapshot":
        root.metadata_json["code_mode_state"]["snapshot_b64"] = "!invalid!"
    elif fault == "missing_state":
        root.metadata_json.pop("code_mode_state")
    else:
        root.metadata_json["code_mode_state"][
            f"{fault}_tool_call_id" if fault == "outer" else "nested_call_id"
        ] = "wrong"
    with pytest.raises(ConflictError):
        project_approval_graph(build_approval_graph(root, {}))


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("deleted", "missing"),
        ("missing", "missing"),
        ("workspace", "invalid"),
        ("user", "invalid"),
        ("parent", "invalid"),
        ("depth", "invalid"),
        ("running", "pending"),
        ("completed", "terminal"),
    ],
)
def test_child_states_are_distinct_and_never_become_direct_approvals(mutation, expected):
    root = saved_run()
    child = saved_run(parent=root)
    delegate(root, [child])
    children = {child.id: child}
    if mutation == "missing":
        children.clear()
    elif mutation == "deleted":
        child.deleted = True
    elif mutation == "depth":
        child.delegation_depth = 2
    elif mutation in ("running", "completed"):
        child.status = mutation
    else:
        setattr(
            child,
            {"workspace": "workspace_id", "user": "user_id", "parent": "parent_run_id"}[mutation],
            uuid4(),
        )
    graph = build_approval_graph(root, children)
    assert isinstance(graph.nodes[0], DelegatedApprovalNode)
    assert graph.nodes[0].status == expected
    with pytest.raises(ConflictError):
        project_approval_graph(graph)


def test_deeper_delegation_and_cycles_fail_closed():
    root = saved_run()
    child = saved_run(parent=root)
    delegate(root, [child])
    delegate(child, [root])
    with pytest.raises(ConflictError, match="Nested delegation"):
        build_approval_graph(root, {child.id: child})
    delegate(root, [root])
    with pytest.raises(ConflictError):
        project_approval_graph(build_approval_graph(root, {root.id: root}))


def test_staged_content_and_entity_display_preserve_executable_proposal():
    args = {"target": {"entity_id": "row-1"}, "records": [{"value": 1}], "locked": "fixed"}
    root = saved_run(
        calls=[ToolCallPart("update", args, "edit")],
        metadata={"edit": {"display_args": {**args, "_entity_label": "Record"}}},
    )
    response = project_approval_graph(build_approval_graph(root, {}))
    assert response.approvals[0].replay_args == args
    assert response.approvals[0].args["_entity_label"] == "Record"
    suspend(
        root,
        [ToolCallPart("write_file", {"name": "report", "content_ref": "content-sha-a"}, "write")],
        {"write": {"display_args": {"name": "report", "content": "[omitted]"}}},
    )
    before = project_approval_graph(build_approval_graph(root, {}))
    root.metadata_json["approval_state"]["deferred_tool_requests"]["approvals"][0]["args"][
        "content_ref"
    ] = "content-sha-b"
    after = project_approval_graph(build_approval_graph(root, {}))
    assert before.approvals[0].args == after.approvals[0].args
    assert before.approval_revision != after.approval_revision


@pytest.mark.parametrize("name", ["delegate_to_agent", "run_workflow"])
@pytest.mark.parametrize("metadata", [None, {"kind": "invalid"}])
def test_missing_specialised_metadata_fails_closed(name, metadata):
    root = saved_run(
        calls=[ToolCallPart(name, {}, "call")], metadata={"call": metadata} if metadata else None
    )
    with pytest.raises(ConflictError):
        build_approval_graph(root, {})


@pytest.mark.parametrize("fault", ["missing", "settled", "duplicate", "arguments", "name"])
def test_pending_trace_cannot_authorise_mismatched_or_settled_calls(fault):
    root = saved_run()
    workflow(root)
    trace = root.metadata_json["code_mode_state"]["nested_trace"]
    if fault == "missing":
        trace.pop()
    elif fault == "settled":
        trace[-1]["status"] = "succeeded"
    elif fault == "duplicate":
        trace.append(deepcopy(trace[-1]))
    elif fault == "arguments":
        trace[-1]["args_sha256"] = "a" * 64
    else:
        trace[-1]["tool_name"] = "other_tool"
    with pytest.raises(ConflictError):
        build_approval_graph(root, {})


def test_snapshot_taint_is_preserved_when_approval_metadata_omits_it():
    root = saved_run()
    workflow(root)
    metadata = root.metadata_json["approval_state"]["deferred_tool_requests"]["metadata"][
        "workflow"
    ]
    metadata["derived_from_untrusted"] = False
    metadata["taint_sources"] = []
    before = project_approval_graph(build_approval_graph(root, {}))
    state = root.metadata_json["code_mode_state"]
    state["tainted"] = True
    state["taint_sources"] = [{"source_kind": "integration", "source_ref": "saved-row"}]
    after = project_approval_graph(build_approval_graph(root, {}))
    assert after.approvals[0].derived_from_untrusted
    assert after.approvals[0].taint_sources == state["taint_sources"]
    assert after.approval_revision != before.approval_revision
