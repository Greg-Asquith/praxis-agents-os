"""Approval identity and projection cases using durable state serializers."""

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ToolCallPart

from core.exceptions.general import ConflictError
from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agents.runtime.approval_identity import APPROVAL_BATCH_KEY, proposal_digest
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


def saved_run(*, parent=None, calls=None, metadata=None, legacy=False):
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
    suspend(
        run, calls or [ToolCallPart("update", {"value": 1}, "same-id")], metadata, legacy=legacy
    )
    return run


def suspend(run, calls, metadata=None, *, legacy=False):
    run.metadata_json = build_suspended_run_metadata(
        run=run,
        conversation=Conversation(id=run.conversation_id),
        message_history=[],
        deferred_tool_requests=DeferredToolRequests(approvals=calls, metadata=metadata or {}),
    )
    if legacy:
        run.metadata_json["approval_state"].pop(APPROVAL_BATCH_KEY)


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


def test_reloads_stable_and_repeated_rounds_have_fresh_identity():
    root = saved_run()
    first = project_approval_graph(build_approval_graph(root, {}))
    saved = deepcopy(root.metadata_json)
    assert project_approval_graph(build_approval_graph(root, {})) == first
    assert root.metadata_json == saved
    suspend(root, [ToolCallPart("update", {"value": 1}, "same-id")])
    second = project_approval_graph(build_approval_graph(root, {}))
    assert second.approvals[0].approval_id != first.approvals[0].approval_id
    assert second.approval_revision != first.approval_revision


def test_legacy_reads_are_pure_and_proposals_change_revision_only():
    root = saved_run(legacy=True)
    before = deepcopy(root.metadata_json)
    first = project_approval_graph(build_approval_graph(root, {}))
    assert project_approval_graph(build_approval_graph(root, {})) == first
    assert root.metadata_json == before
    root.metadata_json["approval_state"]["deferred_tool_requests"]["approvals"][0]["args"][
        "value"
    ] = 9
    changed = project_approval_graph(build_approval_graph(root, {}))
    assert first.approvals[0].approval_id == changed.approvals[0].approval_id
    assert first.approval_revision != changed.approval_revision
    # Editing the public response does not mutate the immutable server proposal.
    changed.approvals[0].args = {"value": 123}
    assert (
        project_approval_graph(build_approval_graph(root, {})).approval_revision
        == changed.approval_revision
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"approval_batch_id": None},
        {"approval_batch_id": "bad"},
        {"approval_revision": None},
        {"approval_revision": "bad"},
        {"approval_revision": "a" * 64},
    ],
)
def test_invalid_present_metadata_never_uses_legacy_identity(fields):
    root = saved_run(legacy=True)
    root.metadata_json["approval_state"].update(fields)
    with pytest.raises(ConflictError):
        build_approval_graph(root, {})


def test_multiple_child_workflows_project_nested_controls_and_denial_evidence():
    root = saved_run()
    children = [saved_run(parent=root), saved_run(parent=root)]
    for child in children:
        workflow(child)
    delegate(root, children)
    response = project_approval_graph(
        build_approval_graph(root, {child.id: child for child in children})
    )
    assert len(response.workflows) == 2
    assert response.workflow is None
    assert len({item.approval_id for item in response.approvals}) == 2
    assert all(
        item.name == "update" and item.parent_tool_call_id == "workflow"
        for item in response.approvals
    )
    assert all(item.derived_from_untrusted and item.taint_sources for item in response.approvals)
    assert all(item.nested_trace[0].status == "denied" for item in response.workflows)
    assert "private-snapshot" not in response.model_dump_json()
    assert "snapshot" not in response.model_dump_json()


def test_single_root_workflow_keeps_legacy_adapter_and_outer_identity():
    root = saved_run()
    workflow(root)
    response = project_approval_graph(build_approval_graph(root, {}))
    assert response.workflow == response.workflows[0]
    assert response.approvals[0].tool_call_id == "same-id"
    assert response.model_dump()["approvals"][0]["parent_tool_call_id"] == "workflow"


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


def test_canonical_digest_is_order_independent_and_bounded():
    assert proposal_digest({"a": 1, "b": 2}) == proposal_digest({"b": 2, "a": 1})
    with pytest.raises(ConflictError):
        proposal_digest({"huge": "x" * (4 * 1024 * 1024)})


@pytest.mark.parametrize("name", ["delegate_to_agent", "run_workflow"])
@pytest.mark.parametrize("metadata", [None, {"kind": "invalid"}])
def test_missing_specialised_metadata_fails_closed(name, metadata):
    root = saved_run(
        calls=[ToolCallPart(name, {}, "call")], metadata={"call": metadata} if metadata else None
    )
    with pytest.raises(ConflictError):
        build_approval_graph(root, {})


@pytest.mark.parametrize("shape", ["direct", "workflow", "delegated", "sibling_workflows"])
def test_stream_and_reload_shapes_share_projection(shape):
    from services.agents.runtime.approval_events import approval_events_for_projection

    root = saved_run()
    children = []
    if shape == "workflow":
        workflow(root)
    if shape in ("delegated", "sibling_workflows"):
        children = [saved_run(parent=root), saved_run(parent=root)]
        if shape == "sibling_workflows":
            for child in children:
                workflow(child)
        delegate(root, children)
    response = project_approval_graph(
        build_approval_graph(root, {child.id: child for child in children})
    )
    events = approval_events_for_projection(response)
    for event, approval in zip(events, response.approvals, strict=True):
        dumped = event.model_dump(mode="json", exclude_none=True)
        assert dumped.pop("approval_revision") == response.approval_revision
        assert dumped == approval.model_dump(mode="json", exclude_none=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [None, "deleted_run", "deleted_conversation", "cross_workspace", "cross_user", "wrong_parent"],
)
async def test_database_loader_validates_links_and_repeated_legacy_reads_do_not_write(
    db_session, fault
):
    from sqlalchemy import event

    from core.database import set_session_tenant_context
    from models.agent import Agent
    from services.agent_runs.load_approval_graph import load_approval_graph
    from tests.factories import build_user, build_workspace, build_workspace_membership

    user = build_user(email=f"approval-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"approval-{uuid4().hex[:8]}")
    db_session.add_all(
        [user, workspace, build_workspace_membership(user_id=user.id, workspace_id=workspace.id)]
    )
    await db_session.flush()
    agent = Agent(
        name="Reviewer",
        slug=f"reviewer-{uuid4().hex[:8]}",
        instructions="Review proposed actions.",
        workspace_id=workspace.id,
        created_by=user.id,
        model_provider="openai",
        model="gpt-5.4-mini",
    )
    db_session.add(agent)
    await db_session.flush()
    root = saved_run(legacy=True)
    root.workspace_id, root.user_id, root.agent_id = workspace.id, user.id, agent.id
    child = saved_run(parent=root, legacy=True)
    child.agent_id = agent.id
    conversations = [
        Conversation(
            id=run.conversation_id,
            user_id=user.id,
            workspace_id=workspace.id,
            created_by=user.id,
            active_agent_id=agent.id,
        )
        for run in (root, child)
    ]
    for run in (root, child):
        suspend(run, [ToolCallPart("update", {"value": 1}, "same-id")], legacy=True)
    delegate(root, [child])
    root.metadata_json["approval_state"].pop(APPROVAL_BATCH_KEY)
    if fault == "deleted_run":
        child.deleted = True
    if fault == "deleted_conversation":
        conversations[1].deleted = True
    if fault == "cross_workspace":
        other_workspace = build_workspace(slug=f"approval-{uuid4().hex[:8]}")
        db_session.add(other_workspace)
        await db_session.flush()
        child.workspace_id = other_workspace.id
    if fault == "cross_user":
        other_user = build_user(email=f"approval-{uuid4().hex}@example.com")
        db_session.add(other_user)
        await db_session.flush()
        child.user_id = other_user.id
    if fault == "wrong_parent":
        child.parent_run_id = None
    db_session.add_all(conversations)
    await db_session.flush()
    db_session.add(root)
    await db_session.flush()
    db_session.add(child)
    await db_session.flush()
    await set_session_tenant_context(db_session, workspace_id=workspace.id, user_id=user.id)
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    before = deepcopy(root.metadata_json)
    try:
        for _ in range(2):
            if fault == "deleted_conversation":
                with pytest.raises(ConflictError):
                    await load_approval_graph(
                        db_session, actor=user, workspace=workspace, run_id=root.id
                    )
                continue
            graph = await load_approval_graph(
                db_session, actor=user, workspace=workspace, run_id=root.id
            )
            if fault is None:
                assert len(project_approval_graph(graph).approvals) == 1
            else:
                with pytest.raises(ConflictError):
                    project_approval_graph(graph)
        assert root.metadata_json == before
        assert not any(
            statement.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))
            for statement in statements
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)


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


@pytest.mark.asyncio
async def test_real_staged_write_serializer_preserves_owned_content_digest(monkeypatch):
    import hashlib
    from unittest.mock import AsyncMock

    from services.agents.runtime import staged_tool_content

    root = saved_run()
    provider = AsyncMock()
    monkeypatch.setattr(staged_tool_content, "get_storage_provider", lambda: provider)
    requests = DeferredToolRequests(
        approvals=[
            ToolCallPart(
                "write_file", {"name": "report.txt", "content": "Confidential report"}, "write"
            )
        ]
    )
    staged = await staged_tool_content.stage_write_file_approval_content(
        workspace_id=root.workspace_id,
        run_id=root.id,
        new_messages=[],
        all_messages=[],
        deferred_tool_requests=requests,
    )
    suspend(root, staged.deferred_tool_requests.approvals, staged.deferred_tool_requests.metadata)
    response = project_approval_graph(build_approval_graph(root, {}))
    pending = response.approvals[0]
    content_hash = hashlib.sha256(b"Confidential report").hexdigest()
    assert pending.args["content_sha256"] == content_hash
    assert pending.replay_args["content_ref"].startswith(
        f"workspaces/{root.workspace_id}/agent-runs/{root.id}/"
    )
    assert content_hash in pending.replay_args["content_ref"]
    assert "Confidential report" not in response.model_dump_json()
    provider.put_object.assert_awaited_once()
