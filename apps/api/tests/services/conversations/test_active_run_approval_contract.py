"""Checks approval revisions on active-run reads without activating projection."""

from uuid import uuid4

import pytest

from core.exceptions.general import ConflictError
from models.agent_run import AgentRun
from services.conversations.active_run import _saved_approval_revision


def test_active_run_revision_reads_saved_value_without_mutating_metadata() -> None:
    from pydantic_ai import DeferredToolRequests
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    from models.conversation import Conversation
    from services.agents.runtime.approval_state import build_suspended_run_metadata

    run = AgentRun(
        id=uuid4(), conversation_id=uuid4(), agent_id=uuid4(), status="awaiting_approval"
    )
    call = ToolCallPart(tool_name="send", tool_call_id="native", args={})
    run.metadata_json = build_suspended_run_metadata(
        run=run,
        conversation=Conversation(id=run.conversation_id),
        message_history=[ModelResponse(parts=[call])],
        deferred_tool_requests=DeferredToolRequests(approvals=[call]),
    )
    state = run.metadata_json["approval_state"]
    state["approval_revision"] = "a" * 64
    assert _saved_approval_revision(run) == "a" * 64
    assert run.metadata_json == {"approval_state": state}
    state["conversation_id"] = str(uuid4())
    with pytest.raises(ConflictError):
        _saved_approval_revision(run)


@pytest.mark.parametrize("state", [{}, {"approval_batch_id": str(uuid4())}])
def test_active_run_revision_keeps_legacy_reads_without_projection(state: dict) -> None:
    run = AgentRun(status="awaiting_approval", metadata_json={"approval_state": state})
    assert _saved_approval_revision(run) is None
    assert _saved_approval_revision(run) is None
    assert run.metadata_json == {"approval_state": state}


@pytest.mark.parametrize(
    "state",
    [
        {"approval_batch_id": "invalid"},
        {"approval_revision": "a" * 64},
        {"approval_batch_id": str(uuid4()), "approval_revision": None},
    ],
)
def test_active_run_revision_rejects_invalid_identity_metadata(state: dict) -> None:
    run = AgentRun(status="awaiting_approval", metadata_json={"approval_state": state})
    with pytest.raises(ConflictError):
        _saved_approval_revision(run)


@pytest.mark.asyncio
async def test_child_root_link_requires_visible_canonical_parent(db_session) -> None:
    from models.agent import Agent
    from services.agent_runs import create_agent_run
    from services.conversations.active_run import _verified_root_run
    from tests.factories import build_conversation, build_user, build_workspace

    user = build_user()
    workspace = build_workspace()
    db_session.add_all([user, workspace])
    await db_session.flush()
    agent = Agent(
        name="Specialist",
        slug=f"specialist-{uuid4().hex[:8]}",
        instructions="Complete assigned work.",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db_session.add(agent)
    await db_session.flush()
    conversation = build_conversation(user=user, workspace=workspace, active_agent_id=agent.id)
    db_session.add(conversation)
    await db_session.flush()
    root = await create_agent_run(
        db_session,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
    )
    child = AgentRun(
        parent_run_id=root.id,
        delegation_depth=1,
        workspace_id=workspace.id,
        user_id=user.id,
    )
    assert await _verified_root_run(db_session, run=child, actor=user, workspace=workspace) is root
    child.delegation_depth = 2
    assert await _verified_root_run(db_session, run=child, actor=user, workspace=workspace) is None
    child.delegation_depth = 1
    assert (
        await _verified_root_run(db_session, run=child, actor=build_user(), workspace=workspace)
        is None
    )
    assert (
        await _verified_root_run(db_session, run=child, actor=user, workspace=build_workspace())
        is None
    )
    conversation.deleted = True
    await db_session.flush()
    assert await _verified_root_run(db_session, run=child, actor=user, workspace=workspace) is None
    conversation.deleted = False
    root.deleted = True
    await db_session.flush()
    assert await _verified_root_run(db_session, run=child, actor=user, workspace=workspace) is None
