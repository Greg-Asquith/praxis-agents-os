"""HTTP and aggregate-contract tests for exact workspace status summaries."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.database import set_session_tenant_context
from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from tests.factories import (
    build_conversation,
    build_user,
    build_workspace,
    build_workspace_membership,
)
from tests.support.auth import bearer_headers


async def _authenticated_workspace(
    db: AsyncSession,
) -> tuple[User, Workspace, Agent, dict[str, str]]:
    user = build_user(email=f"status-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"status-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.MEMBER,
    )
    agent = Agent(
        name="Status agent",
        slug=f"status-agent-{uuid4().hex[:8]}",
        instructions="Summarize workspace activity.",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db.add_all([user, workspace, membership, agent])
    await db.flush()
    user.default_workspace_id = workspace.id
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    headers = {
        **bearer_headers(session["session_token"]),
        "X-Workspace": workspace.slug,
    }
    return user, workspace, agent, headers


def _schedule(
    *,
    user: User,
    workspace: Workspace,
    agent: Agent,
    name: str,
) -> AgentSchedule:
    return AgentSchedule(
        agent_id=agent.id,
        user_id=user.id,
        workspace_id=workspace.id,
        name=name,
        schedule_type="interval",
        interval_minutes=60,
        timezone="UTC",
        default_prompt="Run the scheduled task.",
        is_active=True,
        next_run_at=datetime.now(UTC) + timedelta(hours=1),
    )


def _schedule_run(
    *,
    user: User,
    workspace: Workspace,
    agent: Agent,
    schedule: AgentSchedule,
    status: str,
    scheduled_for: datetime,
    agent_run: AgentRun | None = None,
) -> AgentScheduleRun:
    return AgentScheduleRun(
        schedule_id=schedule.id,
        workspace_id=workspace.id,
        user_id=user.id,
        agent_id=agent.id,
        scheduled_for=scheduled_for,
        status=status,
        attempt_count=1,
        agent_run_id=agent_run.id if agent_run is not None else None,
    )


def _agent_run(
    *,
    user: User,
    workspace: Workspace,
    agent: Agent,
    conversation: Conversation,
    status: str,
    outcome: str | None = None,
) -> AgentRun:
    return AgentRun(
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
        status=status,
        outcome=outcome,
    )


async def test_status_summary_is_empty_for_new_workspace(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, _agent, headers = await _authenticated_workspace(db_session)

    response = await db_async_client.get("/api/v1/status/summary", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "unread_conversations": 0,
        "conversations_needing_approval": 0,
        "schedules_needing_attention": 0,
    }


async def test_status_summary_counts_all_rows_and_latest_schedule_health(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, agent, headers = await _authenticated_workspace(db_session)
    now = datetime.now(UTC)

    unread = [
        build_conversation(
            user=user,
            workspace=workspace,
            title=f"Unread {index}",
            unread=True,
        )
        for index in range(101)
    ]
    db_session.add_all(unread)

    approval_runs: list[AgentRun] = []
    for index in range(101):
        conversation = build_conversation(
            user=user,
            workspace=workspace,
            title=f"Approval {index}",
            unread=True,
        )
        approval_runs.append(
            _agent_run(
                user=user,
                workspace=workspace,
                agent=agent,
                conversation=conversation,
                status="awaiting_approval",
            )
        )
        db_session.add_all([conversation, approval_runs[-1]])

    attention_schedules = [
        _schedule(user=user, workspace=workspace, agent=agent, name=f"Retry {index}")
        for index in range(101)
    ]
    db_session.add_all(attention_schedules)
    await db_session.flush()
    db_session.add_all(
        [
            _schedule_run(
                user=user,
                workspace=workspace,
                agent=agent,
                schedule=schedule,
                status="retryable_failed",
                scheduled_for=now,
            )
            for schedule in attention_schedules
        ]
    )

    boundary_statuses = [
        "pending",
        "claimed",
        "accepted",
        "running",
        "awaiting_approval",
        "completed",
        "terminal_failed",
        "cancelled",
    ]
    boundary_schedules = [
        _schedule(user=user, workspace=workspace, agent=agent, name=status)
        for status in boundary_statuses
    ]
    db_session.add_all(boundary_schedules)
    await db_session.flush()
    db_session.add_all(
        [
            _schedule_run(
                user=user,
                workspace=workspace,
                agent=agent,
                schedule=schedule,
                status=status,
                scheduled_for=now,
            )
            for schedule, status in zip(boundary_schedules, boundary_statuses, strict=True)
        ]
    )

    latest_wins = _schedule(user=user, workspace=workspace, agent=agent, name="Latest wins")
    db_session.add(latest_wins)
    await db_session.flush()
    db_session.add_all(
        [
            _schedule_run(
                user=user,
                workspace=workspace,
                agent=agent,
                schedule=latest_wins,
                status="terminal_failed",
                scheduled_for=now - timedelta(hours=1),
            ),
            _schedule_run(
                user=user,
                workspace=workspace,
                agent=agent,
                schedule=latest_wins,
                status="completed",
                scheduled_for=now,
            ),
        ]
    )

    for outcome in ("gate_failed", "budget_exhausted"):
        conversation = build_conversation(user=user, workspace=workspace, unread=False)
        run = _agent_run(
            user=user,
            workspace=workspace,
            agent=agent,
            conversation=conversation,
            status="completed",
            outcome=outcome,
        )
        schedule = _schedule(user=user, workspace=workspace, agent=agent, name=outcome)
        db_session.add_all([conversation, run, schedule])
        await db_session.flush()
        db_session.add(
            _schedule_run(
                user=user,
                workspace=workspace,
                agent=agent,
                schedule=schedule,
                status="completed",
                scheduled_for=now,
                agent_run=run,
            )
        )

    await db_session.commit()

    response = await db_async_client.get("/api/v1/status/summary", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "unread_conversations": 101,
        "conversations_needing_approval": 101,
        "schedules_needing_attention": 104,
    }


async def test_status_summary_is_workspace_isolated_and_requires_membership(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, _agent, headers = await _authenticated_workspace(db_session)
    visible = build_conversation(user=user, workspace=workspace, unread=True)
    db_session.add(visible)
    await db_session.commit()

    other_user = build_user(email=f"other-status-{uuid4().hex}@example.com")
    other_workspace = build_workspace(slug=f"other-status-{uuid4().hex[:8]}")
    other_membership = build_workspace_membership(
        workspace_id=other_workspace.id,
        user_id=other_user.id,
        role=WorkspaceRole.OWNER,
    )
    db_session.add_all([other_user, other_workspace, other_membership])
    await db_session.flush()
    await set_session_tenant_context(
        db_session,
        workspace_id=other_workspace.id,
        user_id=other_user.id,
    )
    hidden = build_conversation(user=other_user, workspace=other_workspace, unread=True)
    db_session.add(hidden)
    await db_session.commit()
    await set_session_tenant_context(db_session, workspace_id=workspace.id, user_id=user.id)

    response = await db_async_client.get("/api/v1/status/summary", headers=headers)
    forbidden = await db_async_client.get(
        "/api/v1/status/summary",
        headers={**headers, "X-Workspace": other_workspace.slug},
    )
    unauthenticated = await db_async_client.get("/api/v1/status/summary")

    assert response.status_code == 200
    assert response.json()["unread_conversations"] == 1
    assert forbidden.status_code == 403
    assert unauthenticated.status_code == 401
