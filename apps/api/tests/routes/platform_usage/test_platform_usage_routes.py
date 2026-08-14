"""HTTP-boundary tests for platform-wide AI usage routes."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.auth.sessions import session_manager
from core.database import get_maintenance_async_db_session_factory
from core.settings import settings
from models.ai_usage_event import AIUsageEvent
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers


async def _authenticated_owner(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str,
) -> tuple[Workspace, dict[str, str]]:
    async with session_factory() as db:
        user = build_user(email=email)
        workspace = build_workspace(slug=f"platform-route-{uuid4().hex[:8]}")
        db.add_all(
            [
                user,
                workspace,
                build_workspace_membership(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role=WorkspaceRole.OWNER,
                ),
            ]
        )
        await db.flush()
        user.default_workspace_id = workspace.id
        session = await session_manager.create_session(db, str(user.id))
        await db.commit()
    return workspace, bearer_headers(session["session_token"])


def _usage_event(workspace_id, *, tokens: int, requests: int) -> AIUsageEvent:
    return AIUsageEvent(
        workspace_id=workspace_id,
        occurred_at=datetime(2099, 8, 12, 12, tzinfo=UTC),
        provider="openai",
        model="gpt-5.6-luna",
        purpose="agent_run",
        input_tokens=tokens,
        cache_read_tokens=0,
        cache_write_tokens=0,
        output_tokens=0,
        requests=requests,
    )


async def test_platform_usage_routes_require_super_admin_and_expose_no_content(
    app: FastAPI,
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    super_admin_email = f"platform-admin-{uuid4().hex}@example.com"
    ordinary_email = f"platform-owner-{uuid4().hex}@example.com"
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", super_admin_email)
    admin_workspace, admin_headers = await _authenticated_owner(
        committed_db_session_factory,
        email=super_admin_email,
    )
    owner_workspace, owner_headers = await _authenticated_owner(
        committed_db_session_factory,
        email=ordinary_email,
    )
    hidden_workspace = build_workspace(slug=f"platform-hidden-{uuid4().hex[:8]}")
    async with get_maintenance_async_db_session_factory()() as seed_db:
        seed_db.add(hidden_workspace)
        await seed_db.flush()
        seed_db.add_all(
            [
                _usage_event(admin_workspace.id, tokens=10, requests=2),
                _usage_event(owner_workspace.id, tokens=20, requests=3),
                _usage_event(hidden_workspace.id, tokens=30, requests=4),
            ]
        )
        await seed_db.commit()

    params = {
        "from": "2099-08-12T00:00:00Z",
        "to": "2099-08-13T00:00:00Z",
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        denied = await client.get(
            "/api/v1/platform-usage/summary",
            headers=owner_headers,
            params=params,
        )
        assert denied.status_code == 403

        summary = await client.get(
            "/api/v1/platform-usage/summary",
            headers=admin_headers,
            params=params,
        )
        breakdown = await client.get(
            "/api/v1/platform-usage/breakdown",
            headers=admin_headers,
            params={**params, "dimension": "workspace"},
        )

    assert summary.status_code == 200
    summary_body = summary.json()
    assert summary_body["totals"]["tokens_by_class"]["input"] == 60
    assert summary_body["totals"]["requests"] == 9
    assert set(summary_body) == {
        "from",
        "to",
        "timezone",
        "totals",
        "pricing_coverage",
        "daily",
        "models",
    }

    assert breakdown.status_code == 200
    breakdown_body = breakdown.json()
    assert len(breakdown_body["rows"]) == 3
    assert set(breakdown_body) == {"from", "to", "timezone", "dimension", "rows"}
    assert set(breakdown_body["rows"][0]) == {
        "key",
        "label",
        "estimated_cost_usd",
        "tokens_by_class",
        "requests",
        "token_share",
        "priced_cost_share",
        "pricing_coverage",
    }

    async with get_maintenance_async_db_session_factory()() as cleanup_db:
        await cleanup_db.execute(
            delete(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id.in_(
                    [admin_workspace.id, owner_workspace.id, hidden_workspace.id]
                )
            )
        )
        await cleanup_db.execute(
            delete(Workspace).where(
                Workspace.id.in_([admin_workspace.id, owner_workspace.id, hidden_workspace.id])
            )
        )
        await cleanup_db.commit()
