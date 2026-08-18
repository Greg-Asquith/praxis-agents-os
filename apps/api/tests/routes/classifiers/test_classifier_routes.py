"""HTTP-boundary tests for workspace classifier management and discovery."""

import asyncio
import importlib
from uuid import uuid4

import pytest
from fastapi import Request
from httpx2 import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.auth.sessions import session_manager
from core.database import set_session_tenant_context
from core.exceptions.general import ConflictError
from models.audit_event import AuditEvent
from models.classifiers import Classifier
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.audit_events import AuditAction, AuditResourceType
from services.classifiers.schemas import ClassifierCreateRequest
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def _authenticated_workspace(
    db: AsyncSession,
    *,
    role: WorkspaceRole = WorkspaceRole.OWNER,
) -> tuple[User, Workspace, dict[str, str]]:
    user = build_user(email=f"classifier-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"classifiers-{uuid4().hex[:8]}")
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


def _payload(*, name: str = "complaint_triage") -> dict[str, object]:
    return {
        "name": name,
        "display_name": "Complaint triage",
        "description": "Route customer messages by primary intent.",
        "instructions": "Prefer complaint when a customer asks for recovery.",
        "labels": [
            {"label": "complaint", "description": "Needs service recovery."},
            {"label": "other", "description": "Everything else."},
        ],
    }


async def test_classifier_crud_is_audited_and_delete_frees_the_name(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)

    create_response = await db_async_client.post(
        "/api/v1/classifiers/",
        headers=headers,
        json=_payload(),
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["workspace_id"] == str(workspace.id)
    assert created["created_by"] == str(user.id)
    assert [item["label"] for item in created["labels"]] == ["complaint", "other"]

    update_response = await db_async_client.patch(
        f"/api/v1/classifiers/{created['id']}",
        headers=headers,
        json={"display_name": "Support triage", "is_active": False},
    )
    assert update_response.status_code == 200
    assert update_response.json()["display_name"] == "Support triage"
    assert update_response.json()["is_active"] is False

    list_response = await db_async_client.get(
        "/api/v1/classifiers/?include_inactive=true",
        headers=headers,
    )
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    delete_response = await db_async_client.delete(
        f"/api/v1/classifiers/{created['id']}",
        headers=headers,
    )
    assert delete_response.status_code == 204
    assert await db_session.get(Classifier, created["id"]) is None

    recreate_response = await db_async_client.post(
        "/api/v1/classifiers/",
        headers=headers,
        json=_payload(),
    )
    assert recreate_response.status_code == 201

    events = list(
        await db_session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.resource_type == AuditResourceType.CLASSIFIER.value,
                AuditEvent.resource_id == created["id"],
            )
            .order_by(AuditEvent.created_at)
        )
    )
    assert [event.action for event in events] == [
        AuditAction.CREATE.value,
        AuditAction.UPDATE.value,
        AuditAction.DELETE.value,
    ]


async def test_classifier_writes_require_owner_or_admin(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.MEMBER,
    )

    response = await db_async_client.post(
        "/api/v1/classifiers/",
        headers=headers,
        json=_payload(),
    )

    assert response.status_code == 403


async def test_classifier_model_override_can_only_be_cleared_as_a_pair(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session)
    created = await db_async_client.post(
        "/api/v1/classifiers/",
        headers=headers,
        json={
            **_payload(),
            "model_provider": "openai",
            "model": "gpt-5.6-luna",
        },
    )
    assert created.status_code == 201

    partial_clear = await db_async_client.patch(
        f"/api/v1/classifiers/{created.json()['id']}",
        headers=headers,
        json={"model_provider": None},
    )
    assert partial_clear.status_code == 422

    clear = await db_async_client.patch(
        f"/api/v1/classifiers/{created.json()['id']}",
        headers=headers,
        json={"model_provider": None, "model": None},
    )
    assert clear.status_code == 200
    assert clear.json()["model_provider"] is None
    assert clear.json()["model"] is None


async def test_classifier_count_cap_returns_conflict(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session)
    create_service = importlib.import_module("services.classifiers.create_classifier")
    monkeypatch.setattr(create_service, "MAX_CLASSIFIERS_PER_WORKSPACE", 0)

    response = await db_async_client.post(
        "/api/v1/classifiers/",
        headers=headers,
        json=_payload(),
    )

    assert response.status_code == 409


async def test_classifier_count_cap_serializes_concurrent_creates(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex
    user = build_user(email=f"classifier-cap-{suffix}@example.com")
    workspace = build_workspace(slug=f"classifier-cap-{suffix[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
    )
    async with committed_db_session_factory() as db:
        db.add_all([user, workspace, membership])
        await db.commit()

    create_service = importlib.import_module("services.classifiers.create_classifier")
    monkeypatch.setattr(create_service, "MAX_CLASSIFIERS_PER_WORKSPACE", 1)

    async def create_one(name: str) -> str:
        async with committed_db_session_factory() as db:
            await set_session_tenant_context(
                db,
                workspace_id=workspace.id,
                user_id=user.id,
            )
            try:
                await create_service.create_classifier(
                    db,
                    request=Request(
                        {
                            "type": "http",
                            "method": "POST",
                            "path": "/classifiers",
                            "headers": [],
                        }
                    ),
                    actor=user,
                    workspace=workspace,
                    membership=membership,
                    payload=ClassifierCreateRequest.model_validate(_payload(name=name)),
                )
                await db.commit()
                return "created"
            except ConflictError:
                await db.rollback()
                return "conflict"

    try:
        statuses = await asyncio.gather(
            create_one("first_classifier"),
            create_one("second_classifier"),
        )
        assert sorted(statuses) == ["conflict", "created"]
    finally:
        async with committed_db_session_factory() as db:
            await set_session_tenant_context(
                db,
                workspace_id=workspace.id,
                user_id=user.id,
            )
            await db.execute(delete(AuditEvent).where(AuditEvent.workspace_id == workspace.id))
            await db.execute(delete(Classifier).where(Classifier.workspace_id == workspace.id))
            await db.execute(
                delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace.id)
            )
            await db.execute(delete(Workspace).where(Workspace.id == workspace.id))
            await db.execute(delete(User).where(User.id == user.id))
            await db.commit()


async def test_active_classifier_is_workspace_tool_catalog_and_presentation_entry(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session)
    create_response = await db_async_client.post(
        "/api/v1/classifiers/",
        headers=headers,
        json=_payload(),
    )
    assert create_response.status_code == 201
    classifier_id = create_response.json()["id"]

    catalog = await db_async_client.get("/api/v1/tools/catalog", headers=headers)
    presentations = await db_async_client.get("/api/v1/tools/presentations", headers=headers)
    assert catalog.status_code == 200
    assert presentations.status_code == 200
    catalog_entry = next(
        item for item in catalog.json()["tools"] if item["name"] == "classifier_complaint_triage"
    )
    presentation_entry = next(
        item
        for item in presentations.json()["tools"]
        if item["name"] == "classifier_complaint_triage"
    )
    assert catalog_entry["provider"] == "classifier"
    assert catalog_entry["input_schema"]["required"] == ["items"]
    assert presentation_entry["label"] == "Complaint triage"

    deactivate = await db_async_client.patch(
        f"/api/v1/classifiers/{classifier_id}",
        headers=headers,
        json={"is_active": False},
    )
    assert deactivate.status_code == 200
    catalog_after = await db_async_client.get("/api/v1/tools/catalog", headers=headers)
    presentations_after = await db_async_client.get("/api/v1/tools/presentations", headers=headers)
    assert "classifier_complaint_triage" not in {
        item["name"] for item in catalog_after.json()["tools"]
    }
    assert "classifier_complaint_triage" not in {
        item["name"] for item in presentations_after.json()["tools"]
    }


async def test_agents_accept_own_classifier_and_preserve_stale_name_on_update(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session)
    classifier = await db_async_client.post(
        "/api/v1/classifiers/", headers=headers, json=_payload()
    )
    assert classifier.status_code == 201

    agent = await db_async_client.post(
        "/api/v1/agents/",
        headers=headers,
        json={
            "name": "Support router",
            "instructions": "Route support messages.",
            "tool_names": ["classifier_complaint_triage", "web_search"],
            "tool_policies": {"web_search": "approval"},
            "model_provider": "openai",
            "model": "gpt-5.4-mini",
        },
    )
    assert agent.status_code == 201
    assert agent.json()["tool_names"] == ["classifier_complaint_triage", "web_search"]

    deactivate = await db_async_client.patch(
        f"/api/v1/classifiers/{classifier.json()['id']}",
        headers=headers,
        json={"is_active": False},
    )
    assert deactivate.status_code == 200
    update = await db_async_client.patch(
        f"/api/v1/agents/{agent.json()['id']}",
        headers=headers,
        json={"description": "Still safely editable."},
    )
    assert update.status_code == 200
    assert update.json()["tool_names"] == ["classifier_complaint_triage", "web_search"]
    assert update.json()["tool_policies"] == {"web_search": "approval"}


async def test_agent_rejects_other_workspace_and_nonexistent_classifier_names(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _other_user, _other_workspace, other_headers = await _authenticated_workspace(db_session)
    other_classifier = await db_async_client.post(
        "/api/v1/classifiers/",
        headers=other_headers,
        json=_payload(name="private_triage"),
    )
    assert other_classifier.status_code == 201

    _user, _workspace, headers = await _authenticated_workspace(db_session)
    catalog = await db_async_client.get("/api/v1/tools/catalog", headers=headers)
    assert catalog.status_code == 200
    assert "classifier_private_triage" not in {item["name"] for item in catalog.json()["tools"]}
    for tool_name in ("classifier_private_triage", "classifier_missing"):
        response = await db_async_client.post(
            "/api/v1/agents/",
            headers=headers,
            json={
                "name": f"Agent {tool_name}",
                "instructions": "Route support messages.",
                "tool_names": [tool_name],
                "model_provider": "openai",
                "model": "gpt-5.4-mini",
            },
        )
        assert response.status_code == 400
        assert response.json()["field"] == "tool_names"
