"""Route tests for the pending-approvals inbox."""

from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ToolCallPart
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.agent import Agent
from models.conversation import Conversation
from models.workspace import WorkspaceRole
from services.agent_runs import create_agent_run, mark_run_awaiting_approval, start_agent_run
from services.agents.runtime.approval_state import build_suspended_run_metadata
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def test_pending_approvals_route_returns_safe_projection(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user = build_user(email=f"pending-route-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"pending-route-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.MEMBER,
    )
    db_session.add_all([user, workspace, membership])
    await db_session.flush()
    user.default_workspace_id = workspace.id
    agent = Agent(
        name="Route approval agent",
        slug=f"route-approval-agent-{uuid4().hex[:8]}",
        instructions="Use tools carefully.",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db_session.add(agent)
    await db_session.flush()
    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        active_agent_id=agent.id,
        title="Route approval conversation",
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
    call = ToolCallPart(tool_name="send_email", tool_call_id="send-email", args={})
    await start_agent_run(db_session, run)
    run.metadata_json = build_suspended_run_metadata(
        run=run,
        conversation=conversation,
        message_history=[],
        deferred_tool_requests=DeferredToolRequests(approvals=[call]),
    )
    await mark_run_awaiting_approval(db_session, run)
    session = await session_manager.create_session(db_session, str(user.id))
    await db_session.commit()
    headers = {
        **bearer_headers(session["session_token"]),
        "X-Workspace": workspace.slug,
    }

    response = await db_async_client.get(
        "/api/v1/agent-runs/pending-approvals",
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["run_id"] == str(run.id)
    assert body["items"][0]["pending_tool_names"] == ["send_email"]
    assert "args" not in body["items"][0]


async def test_pending_approvals_route_requires_workspace_and_authentication(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user = build_user(email=f"pending-auth-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"pending-auth-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.MEMBER,
    )
    db_session.add_all([user, workspace, membership])
    await db_session.flush()
    user.default_workspace_id = workspace.id
    session = await session_manager.create_session(db_session, str(user.id))
    await db_session.commit()

    missing_workspace = await db_async_client.get(
        "/api/v1/agent-runs/pending-approvals",
        headers=bearer_headers(session["session_token"]),
    )
    unauthenticated = await db_async_client.get(
        "/api/v1/agent-runs/pending-approvals",
        headers={"X-Workspace": workspace.slug},
    )

    assert missing_workspace.status_code == 422
    assert unauthenticated.status_code == 401
