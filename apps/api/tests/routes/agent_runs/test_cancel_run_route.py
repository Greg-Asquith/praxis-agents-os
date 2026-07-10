# apps/api/tests/routes/agent_runs/test_cancel_run_route.py

"""Route tests for cooperative agent-run cancellation."""

from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.agent import Agent
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from services.agent_runs import create_agent_run, start_agent_run
from services.agent_runs.domain import RUN_STATUS_CANCELLED, RUN_STATUS_RUNNING
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def test_cancel_run_route_cancels_owner_run_and_audits(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, _agent, _conversation, run = await _persist_run_context(
        db_session,
        run_owner_role=WorkspaceRole.MEMBER,
    )
    headers = await _headers_for_user(db_session, user, workspace)

    response = await db_async_client.post(f"/api/v1/agent-runs/{run.id}/cancel", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["id"] == str(run.id)
    assert body["run"]["status"] == RUN_STATUS_CANCELLED
    assert body["local_cancel_delivered"] is False

    stored_run = await db_session.get(AgentRun, run.id)
    assert stored_run is not None
    await db_session.refresh(stored_run)
    assert stored_run.status == RUN_STATUS_CANCELLED

    audit_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.resource_type == "agent_run",
            AuditEvent.resource_id == str(run.id),
            AuditEvent.action == "cancel",
        )
    )
    assert audit_event is not None
    assert audit_event.details["operation"] == "cancel"
    assert audit_event.details["previous_status"] == RUN_STATUS_RUNNING


async def test_cancel_run_route_rejects_terminal_run(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, _agent, _conversation, run = await _persist_run_context(db_session)
    headers = await _headers_for_user(db_session, user, workspace)

    first = await db_async_client.post(f"/api/v1/agent-runs/{run.id}/cancel", headers=headers)
    second = await db_async_client.post(f"/api/v1/agent-runs/{run.id}/cancel", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "Agent run is already terminal"


async def test_cancel_run_route_allows_manager_but_rejects_other_member(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    owner, workspace, _agent, _conversation, run = await _persist_run_context(db_session)
    other_member = build_user(email=f"cancel-member-{uuid4().hex}@example.com")
    manager = build_user(email=f"cancel-admin-{uuid4().hex}@example.com")
    db_session.add_all(
        [
            other_member,
            manager,
            build_workspace_membership(
                workspace_id=workspace.id,
                user_id=other_member.id,
                role=WorkspaceRole.MEMBER,
            ),
            build_workspace_membership(
                workspace_id=workspace.id,
                user_id=manager.id,
                role=WorkspaceRole.ADMIN,
            ),
        ]
    )
    await db_session.flush()
    other_member.default_workspace_id = workspace.id
    manager.default_workspace_id = workspace.id
    await db_session.commit()

    member_headers = await _headers_for_user(db_session, other_member, workspace)
    manager_headers = await _headers_for_user(db_session, manager, workspace)

    denied = await db_async_client.post(
        f"/api/v1/agent-runs/{run.id}/cancel",
        headers=member_headers,
    )
    allowed = await db_async_client.post(
        f"/api/v1/agent-runs/{run.id}/cancel",
        headers=manager_headers,
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["run"]["user_id"] == str(owner.id)
    assert allowed.json()["run"]["status"] == RUN_STATUS_CANCELLED


async def _persist_run_context(
    db: AsyncSession,
    *,
    run_owner_role: WorkspaceRole = WorkspaceRole.OWNER,
) -> tuple[User, Workspace, Agent, Conversation, AgentRun]:
    user = build_user(email=f"cancel-owner-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"cancel-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=run_owner_role,
    )
    db.add_all([user, workspace, membership])
    await db.flush()
    user.default_workspace_id = workspace.id

    agent = Agent(
        name="Cancel Route Agent",
        slug=f"cancel-route-agent-{uuid4().hex[:8]}",
        instructions="Reply plainly.",
        workspace_id=workspace.id,
        created_by=user.id,
        model_provider="openai",
        model="gpt-5.4-mini",
    )
    db.add(agent)
    await db.flush()

    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        active_agent_id=agent.id,
    )
    db.add(conversation)
    await db.flush()

    run = await create_agent_run(
        db,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
    )
    await start_agent_run(db, run)
    await db.commit()
    return user, workspace, agent, conversation, run


async def _headers_for_user(
    db: AsyncSession,
    user: User,
    workspace: Workspace,
) -> dict[str, str]:
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    return {
        **bearer_headers(session["session_token"]),
        "X-Workspace": workspace.slug,
    }
