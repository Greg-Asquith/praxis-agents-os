"""Route tests for internal JWT bearer-token workspace confinement."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def _internal_token_context(
    db: AsyncSession,
) -> tuple[User, Workspace, Workspace, AgentScheduleRun]:
    user = build_user(email=f"internal-token-{uuid4().hex}@example.com")
    other_workspace_user = build_user(email=f"other-run-user-{uuid4().hex}@example.com")
    primary_workspace = build_workspace(slug=f"internal-a-{uuid4().hex[:8]}")
    secondary_workspace = build_workspace(slug=f"internal-b-{uuid4().hex[:8]}")
    primary_membership = build_workspace_membership(
        workspace_id=primary_workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
    )
    secondary_membership = build_workspace_membership(
        workspace_id=secondary_workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
    )
    user.default_workspace_id = primary_workspace.id
    agent_id = uuid4()
    schedule_id = uuid4()
    agent = Agent(
        id=agent_id,
        name="Internal Token Agent",
        slug=f"internal-token-agent-{uuid4().hex[:8]}",
        instructions="Run scheduled work.",
        workspace_id=primary_workspace.id,
        created_by=user.id,
        is_active=True,
    )
    schedule = AgentSchedule(
        id=schedule_id,
        agent_id=agent_id,
        user_id=user.id,
        workspace_id=primary_workspace.id,
        schedule_type="interval",
        interval_minutes=15,
        timezone="UTC",
        default_prompt="Run the schedule.",
        is_active=True,
        next_run_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    schedule_run = AgentScheduleRun(
        schedule_id=schedule_id,
        workspace_id=primary_workspace.id,
        user_id=user.id,
        agent_id=agent_id,
        scheduled_for=datetime.now(UTC),
        status="pending",
    )
    db.add_all(
        [
            user,
            other_workspace_user,
            primary_workspace,
            secondary_workspace,
            primary_membership,
            secondary_membership,
            agent,
            schedule,
            schedule_run,
        ]
    )
    await db.flush()
    return user, primary_workspace, secondary_workspace, schedule_run


def _forge_internal_token(**claims: object) -> str:
    payload = {
        "type": "user_session_token",
        "jti": "test-jti",
        "internal": True,
        **claims,
    }
    return jwt.encode(payload, settings.SECRET_KEY.get_secret_value(), algorithm="HS256")


async def _get_schedules(
    client: AsyncClient,
    *,
    token: str,
    workspace_slug: str,
) -> int:
    response = await client.get(
        "/api/v1/schedules/",
        headers={**bearer_headers(token), "X-Workspace": workspace_slug},
    )
    return response.status_code


async def test_internal_token_accepts_matching_workspace_and_schedule_run(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, _secondary_workspace, schedule_run = await _internal_token_context(db_session)
    await db_session.commit()
    token = _forge_internal_token(
        user_id=str(user.id),
        workspace_id=str(workspace.id),
        schedule_run_id=str(schedule_run.id),
    )

    status_code = await _get_schedules(
        db_async_client,
        token=token,
        workspace_slug=workspace.slug,
    )

    assert status_code == 200


@pytest.mark.parametrize(
    "claims",
    [
        {"type": "wrong_type"},
        {"internal": False},
        {"jti": None},
    ],
)
async def test_internal_token_rejects_required_claim_mismatches(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    claims: dict[str, object],
) -> None:
    user, workspace, _secondary_workspace, _schedule_run = await _internal_token_context(db_session)
    await db_session.commit()
    token = _forge_internal_token(
        user_id=str(user.id),
        workspace_id=str(workspace.id),
        **claims,
    )

    status_code = await _get_schedules(
        db_async_client,
        token=token,
        workspace_slug=workspace.slug,
    )

    assert status_code == 401


async def test_internal_token_rejects_schedule_run_workspace_mismatch(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, _workspace, secondary_workspace, schedule_run = await _internal_token_context(db_session)
    await db_session.commit()
    token = _forge_internal_token(
        user_id=str(user.id),
        workspace_id=str(secondary_workspace.id),
        schedule_run_id=str(schedule_run.id),
    )

    status_code = await _get_schedules(
        db_async_client,
        token=token,
        workspace_slug=secondary_workspace.slug,
    )

    assert status_code == 401


async def test_internal_token_rejects_schedule_run_user_mismatch(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, workspace, _secondary_workspace, schedule_run = await _internal_token_context(db_session)
    other_user = build_user(email=f"token-other-user-{uuid4().hex}@example.com")
    db_session.add(other_user)
    await db_session.flush()
    await db_session.commit()
    token = _forge_internal_token(
        user_id=str(other_user.id),
        workspace_id=str(workspace.id),
        schedule_run_id=str(schedule_run.id),
    )

    status_code = await _get_schedules(
        db_async_client,
        token=token,
        workspace_slug=workspace.slug,
    )

    assert status_code == 401


async def test_internal_token_rejects_deleted_schedule_run(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, _secondary_workspace, schedule_run = await _internal_token_context(db_session)
    schedule_run.soft_delete(deleted_by=user.id)
    await db_session.commit()
    token = _forge_internal_token(
        user_id=str(user.id),
        workspace_id=str(workspace.id),
        schedule_run_id=str(schedule_run.id),
    )

    status_code = await _get_schedules(
        db_async_client,
        token=token,
        workspace_slug=workspace.slug,
    )

    assert status_code == 401


async def test_internal_token_is_confined_to_pinned_workspace(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, secondary_workspace, _schedule_run = await _internal_token_context(db_session)
    await db_session.commit()
    token = _forge_internal_token(user_id=str(user.id), workspace_id=str(workspace.id))

    status_code = await _get_schedules(
        db_async_client,
        token=token,
        workspace_slug=secondary_workspace.slug,
    )

    assert status_code == 403


async def test_internal_token_rejects_expired_jwt(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, _secondary_workspace, _schedule_run = await _internal_token_context(db_session)
    await db_session.commit()
    token = _forge_internal_token(
        user_id=str(user.id),
        workspace_id=str(workspace.id),
        exp=datetime.now(UTC) - timedelta(minutes=1),
    )

    status_code = await _get_schedules(
        db_async_client,
        token=token,
        workspace_slug=workspace.slug,
    )

    assert status_code == 401


async def test_internal_token_rejects_invalid_uuid_claims(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, _secondary_workspace, _schedule_run = await _internal_token_context(db_session)
    await db_session.commit()
    token = _forge_internal_token(user_id=str(user.id), workspace_id="not-a-uuid")

    status_code = await _get_schedules(
        db_async_client,
        token=token,
        workspace_slug=workspace.slug,
    )

    assert status_code == 401
