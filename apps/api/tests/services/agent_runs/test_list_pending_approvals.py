"""Tests for the actor-scoped pending-approvals inbox."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ToolCallPart
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs import (
    create_agent_run,
    list_pending_agent_run_approvals,
    mark_run_awaiting_approval,
    start_agent_run,
)
from services.agents.delegation_approval import (
    DELEGATED_APPROVAL_CHILD_AGENT_NAME_KEY,
    DELEGATED_APPROVAL_CHILD_RUN_ID_KEY,
    DELEGATED_APPROVAL_KIND,
    DELEGATED_APPROVAL_KIND_KEY,
)
from services.agents.runtime.approval_state import build_suspended_run_metadata
from tests.factories import build_user, build_workspace
from tests.services.agent_runs.test_approval_state import ApprovalStateContext

pytestmark = pytest.mark.asyncio
pytest_plugins = ("tests.services.agent_runs.test_approval_state",)


async def test_list_pending_approvals_returns_tool_names_oldest_first(
    db_session: AsyncSession,
    approval_context: ApprovalStateContext,
) -> None:
    first_run = await db_session.get(AgentRun, approval_context.run_id)
    conversation = await db_session.get(Conversation, approval_context.conversation_id)
    assert first_run is not None
    assert conversation is not None
    conversation.title = "Quarterly review"

    newer_run = await create_agent_run(
        db_session,
        conversation_id=conversation.id,
        agent_id=approval_context.agent_id,
        workspace_id=approval_context.workspace.id,
        user_id=approval_context.user.id,
        trigger="interactive",
    )
    oldest = datetime.now(UTC) - timedelta(hours=2)
    newer = datetime.now(UTC) - timedelta(minutes=30)
    await _suspend_run(
        db_session,
        run=first_run,
        conversation=conversation,
        tool_name="send_report",
        awaiting_since=oldest,
    )
    await _suspend_run(
        db_session,
        run=newer_run,
        conversation=conversation,
        tool_name="update_record",
        awaiting_since=newer,
    )

    response = await list_pending_agent_run_approvals(
        db_session,
        actor=approval_context.user,
        workspace=approval_context.workspace,
    )

    assert [item.run_id for item in response.items] == [first_run.id, newer_run.id]
    assert response.items[0].conversation_title == "Quarterly review"
    assert response.items[0].agent_name == "Approval Agent"
    assert response.items[0].pending_tool_names == ["send_report"]
    assert response.items[0].awaiting_since == oldest


async def test_list_pending_approvals_enforces_scope_and_projects_delegation(
    db_session: AsyncSession,
    approval_context: ApprovalStateContext,
) -> None:
    parent = await db_session.get(AgentRun, approval_context.run_id)
    parent_conversation = await db_session.get(
        Conversation,
        approval_context.conversation_id,
    )
    assert parent is not None
    assert parent_conversation is not None

    child_agent = Agent(
        name="Finance delegate",
        slug=f"finance-delegate-{uuid4().hex[:8]}",
        instructions="Handle finance work.",
        workspace_id=approval_context.workspace.id,
        created_by=approval_context.user.id,
    )
    db_session.add(child_agent)
    await db_session.flush()
    child_conversation = Conversation(
        user_id=approval_context.user.id,
        workspace_id=approval_context.workspace.id,
        created_by=approval_context.user.id,
        active_agent_id=child_agent.id,
        source="delegated",
    )
    db_session.add(child_conversation)
    await db_session.flush()
    child = await create_agent_run(
        db_session,
        conversation_id=child_conversation.id,
        agent_id=child_agent.id,
        workspace_id=approval_context.workspace.id,
        user_id=approval_context.user.id,
        trigger="delegated",
        parent_run_id=parent.id,
        delegation_depth=1,
    )
    await _suspend_run(
        db_session,
        run=child,
        conversation=child_conversation,
        tool_name="create_invoice",
    )
    await _suspend_run(
        db_session,
        run=parent,
        conversation=parent_conversation,
        tool_name="delegate_to_agent",
        metadata={
            DELEGATED_APPROVAL_KIND_KEY: DELEGATED_APPROVAL_KIND,
            DELEGATED_APPROVAL_CHILD_RUN_ID_KEY: str(child.id),
            DELEGATED_APPROVAL_CHILD_AGENT_NAME_KEY: child_agent.name,
        },
    )

    other_user = build_user(email=f"pending-other-{uuid4().hex}@example.com")
    other_workspace = build_workspace(slug=f"pending-other-{uuid4().hex[:8]}")
    db_session.add_all([other_user, other_workspace])
    await db_session.flush()
    other_agent = Agent(
        name="Other agent",
        slug=f"other-agent-{uuid4().hex[:8]}",
        instructions="Work elsewhere.",
        workspace_id=approval_context.workspace.id,
        created_by=other_user.id,
    )
    db_session.add(other_agent)
    await db_session.flush()
    other_conversation = Conversation(
        user_id=other_user.id,
        workspace_id=approval_context.workspace.id,
        created_by=other_user.id,
        active_agent_id=other_agent.id,
    )
    db_session.add(other_conversation)
    await db_session.flush()
    other_user_run = await create_agent_run(
        db_session,
        conversation_id=other_conversation.id,
        agent_id=other_agent.id,
        workspace_id=approval_context.workspace.id,
        user_id=other_user.id,
        trigger="interactive",
    )
    await _suspend_run(
        db_session,
        run=other_user_run,
        conversation=other_conversation,
        tool_name="other_user_tool",
    )

    other_workspace_agent = Agent(
        name="Other workspace agent",
        slug=f"other-workspace-agent-{uuid4().hex[:8]}",
        instructions="Work elsewhere.",
        workspace_id=other_workspace.id,
        created_by=approval_context.user.id,
    )
    db_session.add(other_workspace_agent)
    await db_session.flush()
    other_workspace_conversation = Conversation(
        user_id=approval_context.user.id,
        workspace_id=other_workspace.id,
        created_by=approval_context.user.id,
        active_agent_id=other_workspace_agent.id,
    )
    db_session.add(other_workspace_conversation)
    await db_session.flush()
    other_workspace_run = await create_agent_run(
        db_session,
        conversation_id=other_workspace_conversation.id,
        agent_id=other_workspace_agent.id,
        workspace_id=other_workspace.id,
        user_id=approval_context.user.id,
        trigger="interactive",
    )
    await _suspend_run(
        db_session,
        run=other_workspace_run,
        conversation=other_workspace_conversation,
        tool_name="other_workspace_tool",
    )

    deleted_run = await create_agent_run(
        db_session,
        conversation_id=parent_conversation.id,
        agent_id=approval_context.agent_id,
        workspace_id=approval_context.workspace.id,
        user_id=approval_context.user.id,
        trigger="interactive",
    )
    await _suspend_run(
        db_session,
        run=deleted_run,
        conversation=parent_conversation,
        tool_name="deleted_tool",
    )
    deleted_run.deleted = True

    await create_agent_run(
        db_session,
        conversation_id=parent_conversation.id,
        agent_id=approval_context.agent_id,
        workspace_id=approval_context.workspace.id,
        user_id=approval_context.user.id,
        trigger="interactive",
    )
    await db_session.flush()

    response = await list_pending_agent_run_approvals(
        db_session,
        actor=approval_context.user,
        workspace=approval_context.workspace,
    )

    assert response.total == 1
    assert [item.run_id for item in response.items] == [parent.id]
    assert response.items[0].pending_tool_names == []
    assert response.items[0].delegated_agent_names == ["Finance delegate"]


async def test_list_pending_approvals_total_exceeds_limit(
    db_session: AsyncSession,
    approval_context: ApprovalStateContext,
) -> None:
    conversation = await db_session.get(Conversation, approval_context.conversation_id)
    first_run = await db_session.get(AgentRun, approval_context.run_id)
    assert conversation is not None
    assert first_run is not None
    await _suspend_run(
        db_session,
        run=first_run,
        conversation=conversation,
        tool_name="first_tool",
    )
    second_run = await create_agent_run(
        db_session,
        conversation_id=conversation.id,
        agent_id=approval_context.agent_id,
        workspace_id=approval_context.workspace.id,
        user_id=approval_context.user.id,
        trigger="interactive",
    )
    await _suspend_run(
        db_session,
        run=second_run,
        conversation=conversation,
        tool_name="second_tool",
    )

    response = await list_pending_agent_run_approvals(
        db_session,
        actor=approval_context.user,
        workspace=approval_context.workspace,
        limit=1,
    )

    assert response.total == 2
    assert len(response.items) == 1


async def test_list_pending_approvals_skips_corrupt_state(
    db_session: AsyncSession,
    approval_context: ApprovalStateContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        "services.agent_runs.list_pending_approvals.logger.warning",
        lambda message, *args, **kwargs: warnings.append(message),
    )
    run = await db_session.get(AgentRun, approval_context.run_id)
    assert run is not None
    await start_agent_run(db_session, run)
    await mark_run_awaiting_approval(db_session, run)

    response = await list_pending_agent_run_approvals(
        db_session,
        actor=approval_context.user,
        workspace=approval_context.workspace,
    )

    assert response.total == 1
    assert response.items == []
    assert warnings == ["Skipping pending approval run with invalid suspended state"]


async def _suspend_run(
    db: AsyncSession,
    *,
    run: AgentRun,
    conversation: Conversation,
    tool_name: str,
    metadata: dict[str, object] | None = None,
    awaiting_since: datetime | None = None,
) -> None:
    call = ToolCallPart(
        tool_name=tool_name,
        tool_call_id=f"{tool_name}-{run.id}",
        args={},
    )
    requests = DeferredToolRequests(
        approvals=[call],
        metadata={call.tool_call_id: metadata} if metadata is not None else {},
    )
    await start_agent_run(db, run)
    run.metadata_json = build_suspended_run_metadata(
        run=run,
        conversation=conversation,
        message_history=[],
        deferred_tool_requests=requests,
    )
    await mark_run_awaiting_approval(db, run)
    if awaiting_since is not None:
        run.updated_at = awaiting_since
        await db.flush()
