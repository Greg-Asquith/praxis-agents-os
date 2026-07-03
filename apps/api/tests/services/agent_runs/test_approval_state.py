# apps/api/tests/services/agent_runs/test_approval_state.py

"""Tests for reading pending agent-run approval details."""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pydantic_ai import DeferredToolRequests
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError, NotFoundError
from models.agent import Agent
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace
from services.agent_runs import (
    complete_agent_run,
    create_agent_run,
    get_agent_run_approval_state,
    mark_run_awaiting_approval,
    start_agent_run,
)
from services.agents.runtime.execute_run import execute_run
from services.agents.runtime.sinks import CollectingSink
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio


@dataclass(frozen=True)
class ApprovalStateContext:
    user: User
    workspace: Workspace
    agent_id: UUID
    conversation_id: UUID
    run_id: UUID


@pytest_asyncio.fixture
async def approval_context(db_session: AsyncSession) -> ApprovalStateContext:
    user = build_user(email=f"approval-state-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"approval-state-{uuid4().hex[:8]}")
    db_session.add_all([user, workspace])
    await db_session.flush()

    agent = Agent(
        name="Approval Agent",
        slug=f"approval-agent-{uuid4().hex[:8]}",
        instructions="Use tools when helpful.",
        workspace_id=workspace.id,
        created_by=user.id,
        model_provider="openai",
        model="gpt-5.4-mini",
        tool_names=["test_add_numbers"],
        tool_policies={"test_add_numbers": "approval"},
    )
    db_session.add(agent)
    await db_session.flush()

    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        active_agent_id=agent.id,
    )
    db_session.add(conversation)
    await db_session.flush()

    run = await create_agent_run(
        db_session,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
    )

    return ApprovalStateContext(
        user=user,
        workspace=workspace,
        agent_id=agent.id,
        conversation_id=conversation.id,
        run_id=run.id,
    )


async def test_get_approval_state_returns_safe_pending_tool_details(
    db_session: AsyncSession,
    approval_context: ApprovalStateContext,
) -> None:
    result = await execute_run(
        db_session,
        conversation_id=approval_context.conversation_id,
        run_id=approval_context.run_id,
        user_prompt="Add two numbers",
        sink=CollectingSink(
            run_id=approval_context.run_id,
            conversation_id=approval_context.conversation_id,
        ),
        model=TestModel(call_tools=["test_add_numbers"]),
    )
    assert isinstance(result.output, DeferredToolRequests)

    response = await get_agent_run_approval_state(
        db_session,
        actor=approval_context.user,
        workspace=approval_context.workspace,
        run_id=approval_context.run_id,
    )

    assert response.run_id == approval_context.run_id
    assert response.conversation_id == approval_context.conversation_id
    assert len(response.approvals) == 1
    approval = response.approvals[0]
    assert approval.tool_call_id == result.output.approvals[0].tool_call_id
    assert approval.name == "test_add_numbers"
    assert approval.args == {"a": 0, "b": 0}
    assert "message_history" not in response.model_dump()


async def test_get_approval_state_rejects_completed_run(
    db_session: AsyncSession,
    approval_context: ApprovalStateContext,
) -> None:
    run = await db_session.get(Agent, approval_context.agent_id)
    assert run is not None

    agent_run = await create_agent_run(
        db_session,
        conversation_id=approval_context.conversation_id,
        agent_id=approval_context.agent_id,
        workspace_id=approval_context.workspace.id,
        user_id=approval_context.user.id,
        trigger="interactive",
    )
    await start_agent_run(db_session, agent_run)
    await complete_agent_run(db_session, agent_run)

    with pytest.raises(ConflictError, match="not awaiting approval"):
        await get_agent_run_approval_state(
            db_session,
            actor=approval_context.user,
            workspace=approval_context.workspace,
            run_id=agent_run.id,
        )


async def test_get_approval_state_respects_user_and_workspace_scope(
    db_session: AsyncSession,
    approval_context: ApprovalStateContext,
) -> None:
    other_user = build_user(email=f"approval-other-{uuid4().hex}@example.com")
    other_workspace = build_workspace(slug=f"approval-other-{uuid4().hex[:8]}")
    db_session.add_all([other_user, other_workspace])
    await db_session.flush()

    with pytest.raises(NotFoundError):
        await get_agent_run_approval_state(
            db_session,
            actor=other_user,
            workspace=approval_context.workspace,
            run_id=approval_context.run_id,
        )

    with pytest.raises(NotFoundError):
        await get_agent_run_approval_state(
            db_session,
            actor=approval_context.user,
            workspace=other_workspace,
            run_id=approval_context.run_id,
        )


async def test_get_approval_state_rejects_missing_suspended_state(
    db_session: AsyncSession,
    approval_context: ApprovalStateContext,
) -> None:
    agent_run = await create_agent_run(
        db_session,
        conversation_id=approval_context.conversation_id,
        agent_id=approval_context.agent_id,
        workspace_id=approval_context.workspace.id,
        user_id=approval_context.user.id,
        trigger="interactive",
    )
    await start_agent_run(db_session, agent_run)
    await mark_run_awaiting_approval(db_session, agent_run)

    with pytest.raises(ConflictError, match="no suspended approval state"):
        await get_agent_run_approval_state(
            db_session,
            actor=approval_context.user,
            workspace=approval_context.workspace,
            run_id=agent_run.id,
        )
