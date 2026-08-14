"""HTTP-boundary tests for workspace AI usage routes."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.database import set_session_tenant_context
from models.ai_usage_event import AIUsageEvent
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def _authenticated_workspace(
    db: AsyncSession,
    *,
    role: WorkspaceRole = WorkspaceRole.OWNER,
    workspace: Workspace | None = None,
) -> tuple[User, Workspace, dict[str, str]]:
    user = build_user(email=f"usage-route-{uuid4().hex}@example.com")
    workspace = workspace or build_workspace(slug=f"usage-route-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
    db.add_all([user, workspace, membership])
    await db.flush()
    user.default_workspace_id = workspace.id
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    return user, workspace, bearer_headers(session["session_token"])


def _usage_event(workspace_id, *, tokens: int, requests: int) -> AIUsageEvent:
    return AIUsageEvent(
        workspace_id=workspace_id,
        occurred_at=datetime(2026, 8, 12, 12, tzinfo=UTC),
        provider="openai",
        model="gpt-5.6-luna",
        purpose="agent_run",
        input_tokens=tokens,
        cache_read_tokens=0,
        cache_write_tokens=0,
        output_tokens=0,
        requests=requests,
    )


async def test_usage_routes_require_workspace_manager(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _owner, workspace, owner_headers = await _authenticated_workspace(db_session)
    _admin, _workspace, admin_headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.ADMIN,
        workspace=workspace,
    )
    _member, _workspace, member_headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.MEMBER,
        workspace=workspace,
    )
    _reader, _workspace, reader_headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.READ_ONLY,
        workspace=workspace,
    )

    params = {
        "from": "2026-08-12T00:00:00Z",
        "to": "2026-08-13T00:00:00Z",
    }
    for headers in (owner_headers, admin_headers):
        summary = await db_async_client.get("/api/v1/usage/summary", headers=headers, params=params)
        breakdown = await db_async_client.get(
            "/api/v1/usage/breakdown",
            headers=headers,
            params={**params, "dimension": "model"},
        )
        assert summary.status_code == 200
        assert breakdown.status_code == 200

    for headers in (member_headers, reader_headers):
        response = await db_async_client.get(
            "/api/v1/usage/summary",
            headers=headers,
            params=params,
        )
        assert response.status_code == 403


async def test_usage_summary_is_explicitly_workspace_scoped(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    owner, workspace, headers = await _authenticated_workspace(db_session)
    other_workspace = build_workspace(slug=f"usage-hidden-{uuid4().hex[:8]}")
    db_session.add(other_workspace)
    await db_session.flush()

    await set_session_tenant_context(
        db_session,
        workspace_id=workspace.id,
        user_id=owner.id,
    )
    db_session.add(_usage_event(workspace.id, tokens=10, requests=2))
    await db_session.flush()
    await set_session_tenant_context(
        db_session,
        workspace_id=other_workspace.id,
        user_id=owner.id,
    )
    db_session.add(_usage_event(other_workspace.id, tokens=999, requests=99))
    await db_session.flush()
    await db_session.commit()

    response = await db_async_client.get(
        "/api/v1/usage/summary",
        headers=headers,
        params={
            "from": "2026-08-12T00:00:00Z",
            "to": "2026-08-13T00:00:00Z",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["from"] == "2026-08-12T00:00:00Z"
    assert body["timezone"] == "UTC"
    assert body["totals"]["tokens_by_class"]["input"] == 10
    assert body["totals"]["requests"] == 2
    assert isinstance(body["totals"]["estimated_cost_usd"], str)
