# apps/api/tests/routes/agents/test_agent_routes.py

"""HTTP-boundary tests for workspace agent configuration routes."""

from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.agent import Agent
from models.audit_event import AuditEvent
from models.skills import Skill
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from services.audit_events import AuditAction, AuditResourceType
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def _authenticated_workspace(
    db: AsyncSession,
    *,
    role: WorkspaceRole = WorkspaceRole.OWNER,
) -> tuple[User, Workspace, dict[str, str]]:
    user = build_user(email=f"agent-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"agents-{uuid4().hex[:8]}")
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


async def test_create_agent_route_persists_public_model_shape(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    skill = Skill(
        name="research",
        human_name="Research",
        description="Research guidance",
        instructions="Use verified sources.",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    delegate = Agent(
        name="Delegate Agent",
        slug=f"delegate-{uuid4().hex[:8]}",
        instructions="Delegate.",
        workspace_id=workspace.id,
        created_by=user.id,
        model_provider="openai",
        model="gpt-5.4-mini",
    )
    db_session.add_all([skill, delegate])
    await db_session.commit()

    response = await db_async_client.post(
        "/api/v1/agents/",
        headers=headers,
        json={
            "name": " Research Agent ",
            "description": " Plans research ",
            "instructions": " Answer carefully. ",
            "tool_names": [
                "web_search",
                "write_todos",
                "read_todos",
                "google_ads_get_report_field",
                "google_ads_list_report_fields",
            ],
            "tool_policies": {
                "web_search": "auto",
                "write_todos": "approval",
                "google_ads_get_report_field": "approval",
                "google_ads_list_report_fields": "approval",
            },
            "code_mode_enabled": True,
            "skill_ids": [str(skill.id)],
            "allowed_agent_ids": [str(delegate.id)],
            "model_provider": "OPENAI",
            "model": "gpt-5.4-mini",
            "model_settings": {"temperature": 0.2, "thinking": "high"},
            "max_steps": 12,
            "is_favorite": True,
            "metadata": {"accent": "green"},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Research Agent"
    assert body["slug"] == "research-agent"
    assert body["workspace_id"] == str(workspace.id)
    assert body["created_by"] == str(user.id)
    assert body["tool_names"] == ["web_search"]
    assert body["tool_policies"] == {"web_search": "auto"}
    assert body["code_mode_enabled"] is True
    assert body["skill_ids"] == [str(skill.id)]
    assert body["allowed_agent_ids"] == [str(delegate.id)]
    assert body["model_provider"] == "openai"
    assert body["model"] == "gpt-5.4-mini"
    assert body["model_settings"] == {"temperature": 0.2, "thinking": "high"}
    assert body["metadata"] == {"accent": "green"}

    fetch_response = await db_async_client.get(
        f"/api/v1/agents/{body['id']}",
        headers=headers,
    )
    assert fetch_response.status_code == 200
    assert fetch_response.json()["metadata"] == {"accent": "green"}
    assert fetch_response.json()["code_mode_enabled"] is True

    audit_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.CREATE.value,
            AuditEvent.resource_type == AuditResourceType.AGENT.value,
            AuditEvent.resource_id == body["id"],
        )
    )
    assert audit_event is not None
    assert audit_event.details["slug"] == "research-agent"


async def test_update_and_delete_agent_routes_apply_workspace_write_access(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    agent = Agent(
        name="Draft Agent",
        slug=f"draft-{uuid4().hex[:8]}",
        instructions="Draft.",
        workspace_id=workspace.id,
        created_by=user.id,
        tool_names=["web_search", "write_todos"],
        tool_policies={"web_search": "auto", "write_todos": "approval"},
        model_provider="openai",
        model="gpt-5.4-mini",
    )
    db_session.add(agent)
    await db_session.commit()

    update_response = await db_async_client.patch(
        f"/api/v1/agents/{agent.id}",
        headers=headers,
        json={
            "name": "Production Agent",
            "tool_names": [
                "web_search",
                "read_todos",
                "google_ads_get_report_field",
                "google_ads_list_report_fields",
            ],
            "tool_policies": {
                "web_search": "auto",
                "google_ads_get_report_field": "approval",
                "google_ads_list_report_fields": "approval",
            },
            "code_mode_enabled": True,
            "is_active": False,
            "metadata": {"stage": "prod"},
        },
    )

    assert update_response.status_code == 200
    update_body = update_response.json()
    assert update_body["name"] == "Production Agent"
    assert update_body["tool_names"] == ["web_search"]
    assert update_body["tool_policies"] == {"web_search": "auto"}
    assert update_body["code_mode_enabled"] is True
    assert update_body["is_active"] is False
    assert update_body["metadata"] == {"stage": "prod"}

    delete_response = await db_async_client.delete(
        f"/api/v1/agents/{agent.id}",
        headers=headers,
    )

    assert delete_response.status_code == 204
    await db_session.refresh(agent)
    assert agent.deleted is True
    assert agent.deleted_by == user.id

    fetch_deleted_response = await db_async_client.get(
        f"/api/v1/agents/{agent.id}",
        headers=headers,
    )
    assert fetch_deleted_response.status_code == 404


async def test_read_only_members_cannot_create_agents(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.READ_ONLY,
    )

    response = await db_async_client.post(
        "/api/v1/agents/",
        headers=headers,
        json={"name": "Blocked", "instructions": "No writes."},
    )

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "Requires workspace write access"
