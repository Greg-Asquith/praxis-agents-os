# apps/api/tests/routes/skills/test_skill_routes.py

"""HTTP-boundary tests for workspace skill routes."""

from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.audit_event import AuditEvent
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from services.audit_events import AuditAction, AuditResourceType
from tests.factories import (
    build_skill,
    build_user,
    build_workspace,
    build_workspace_membership,
)
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def _authenticated_workspace(
    db: AsyncSession,
    *,
    role: WorkspaceRole = WorkspaceRole.OWNER,
) -> tuple[User, Workspace, dict[str, str]]:
    user = build_user(email=f"skill-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"skills-{uuid4().hex[:8]}")
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


async def test_create_skill_route_persists_public_model_shape_and_audit(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)

    response = await db_async_client.post(
        "/api/v1/skills/",
        headers=headers,
        json={
            "name": " research ",
            "human_name": " Research ",
            "description": " Use verified sources. ",
            "instructions": " Follow the research workflow. ",
            "is_favorite": True,
            "metadata": {"accent": "green"},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "research"
    assert body["human_name"] == "Research"
    assert body["description"] == "Use verified sources."
    assert body["instructions"] == "Follow the research workflow."
    assert body["workspace_id"] == str(workspace.id)
    assert body["created_by"] == str(user.id)
    assert body["documentation_refs"] == {}
    assert body["is_active"] is True
    assert body["is_favorite"] is True
    assert body["metadata"] == {"accent": "green"}

    audit_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.CREATE.value,
            AuditEvent.resource_type == AuditResourceType.SKILL.value,
            AuditEvent.resource_id == body["id"],
        )
    )
    assert audit_event is not None
    assert audit_event.details["skill_name"] == "research"


async def test_create_skill_duplicate_name_returns_conflict(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    db_session.add(
        build_skill(
            workspace=workspace,
            created_by=user,
            name="research",
        )
    )
    await db_session.commit()

    response = await db_async_client.post(
        "/api/v1/skills/",
        headers=headers,
        json={
            "name": "research",
            "description": "Duplicate.",
            "instructions": "Should conflict.",
        },
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "A skill with this name already exists in the workspace"


@pytest.mark.parametrize("name", ["Bad Name", "-leading", "a" * 65])
async def test_create_skill_rejects_invalid_name(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    name: str,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session)

    response = await db_async_client.post(
        "/api/v1/skills/",
        headers=headers,
        json={
            "name": name,
            "description": "Invalid.",
            "instructions": "Should fail validation.",
        },
    )

    assert response.status_code == 422


async def test_list_skills_filters_inactive_and_deleted_unless_requested(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    active = build_skill(workspace=workspace, created_by=user, name="active")
    inactive = build_skill(
        workspace=workspace,
        created_by=user,
        name="inactive",
        is_active=False,
    )
    deleted = build_skill(workspace=workspace, created_by=user, name="deleted")
    deleted.soft_delete(deleted_by=user.id, cascade=False)
    db_session.add_all([active, inactive, deleted])
    await db_session.commit()

    response = await db_async_client.get("/api/v1/skills/", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [skill["id"] for skill in body["skills"]] == [str(active.id)]

    include_inactive_response = await db_async_client.get(
        "/api/v1/skills/?include_inactive=true",
        headers=headers,
    )

    assert include_inactive_response.status_code == 200
    include_inactive_body = include_inactive_response.json()
    assert include_inactive_body["total"] == 2
    assert {skill["id"] for skill in include_inactive_body["skills"]} == {
        str(active.id),
        str(inactive.id),
    }


async def test_get_update_and_delete_skill_routes_apply_workspace_scope(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    skill = build_skill(workspace=workspace, created_by=user, name="draft")
    db_session.add(skill)
    await db_session.commit()

    get_response = await db_async_client.get(
        f"/api/v1/skills/{skill.id}",
        headers=headers,
    )
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "draft"

    update_response = await db_async_client.patch(
        f"/api/v1/skills/{skill.id}",
        headers=headers,
        json={
            "name": "production",
            "human_name": "",
            "description": "Production guidance.",
            "is_active": False,
            "metadata": {"stage": "prod"},
        },
    )

    assert update_response.status_code == 200
    update_body = update_response.json()
    assert update_body["name"] == "production"
    assert update_body["human_name"] is None
    assert update_body["description"] == "Production guidance."
    assert update_body["is_active"] is False
    assert update_body["metadata"] == {"stage": "prod"}

    audit_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.UPDATE.value,
            AuditEvent.resource_type == AuditResourceType.SKILL.value,
            AuditEvent.resource_id == str(skill.id),
        )
    )
    assert audit_event is not None
    assert audit_event.details["changed_fields"] == [
        "name",
        "human_name",
        "description",
        "is_active",
        "metadata_json",
    ]

    delete_response = await db_async_client.delete(
        f"/api/v1/skills/{skill.id}",
        headers=headers,
    )

    assert delete_response.status_code == 204
    await db_session.refresh(skill)
    assert skill.deleted is True
    assert skill.deleted_by == user.id

    fetch_deleted_response = await db_async_client.get(
        f"/api/v1/skills/{skill.id}",
        headers=headers,
    )
    assert fetch_deleted_response.status_code == 404


async def test_get_skill_from_another_workspace_returns_not_found(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, _workspace, headers = await _authenticated_workspace(db_session)
    other_workspace = build_workspace(slug=f"other-{uuid4().hex[:8]}")
    other_skill = build_skill(
        workspace=other_workspace,
        created_by=user,
        name="other-skill",
    )
    db_session.add_all([other_workspace, other_skill])
    await db_session.commit()

    response = await db_async_client.get(
        f"/api/v1/skills/{other_skill.id}",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["resource_type"] == "skill"


async def test_update_skill_rejects_null_name(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    skill = build_skill(workspace=workspace, created_by=user, name="draft")
    db_session.add(skill)
    await db_session.commit()

    response = await db_async_client.patch(
        f"/api/v1/skills/{skill.id}",
        headers=headers,
        json={"name": None},
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["field"] == "name"


async def test_unauthenticated_skill_request_returns_unauthorized(
    db_async_client: AsyncClient,
) -> None:
    response = await db_async_client.get("/api/v1/skills/")

    assert response.status_code == 401
