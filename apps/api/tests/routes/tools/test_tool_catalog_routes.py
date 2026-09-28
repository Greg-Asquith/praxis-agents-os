# apps/api/tests/routes/tools/test_tool_catalog_routes.py

"""HTTP-boundary tests for runtime tool catalog routes."""

from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.database import set_session_tenant_context
from core.settings import settings
from models.agent import Agent
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.factories.files import build_file
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def _authenticated_workspace(
    db: AsyncSession,
    *,
    role: WorkspaceRole = WorkspaceRole.READ_ONLY,
) -> tuple[User, Workspace, dict[str, str]]:
    user = build_user(email=f"tools-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"tools-{uuid4().hex[:8]}")
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


async def test_tool_catalog_route_returns_configurable_entries_for_workspace_member(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session)

    response = await db_async_client.get("/api/v1/tools/catalog", headers=headers)

    assert response.status_code == 200
    body = response.json()
    catalog_names = {tool["name"] for tool in body["tools"]}
    assert "google_ads_get_report_field" not in catalog_names
    assert "google_ads_list_report_fields" not in catalog_names
    web_search = next(tool for tool in body["tools"] if tool["name"] == "web_search")
    assert web_search["default_policy"] == "approval"
    assert web_search["input_schema"]["required"] == ["query"]
    assert "timeout" not in web_search


async def test_tool_catalog_route_hides_helper_tools_without_configured_providers(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)

    response = await db_async_client.get("/api/v1/tools/catalog", headers=headers)

    assert response.status_code == 200
    names = {tool["name"] for tool in response.json()["tools"]}
    assert "web_search" not in names
    assert "classify" not in names


@pytest.mark.parametrize(
    ("provider", "google_vertex_ai"),
    [("google", True), ("openai", False)],
    ids=["google-vertex-ai", "openai"],
)
async def test_tool_catalog_route_exposes_generate_image_for_supported_provider(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    google_vertex_ai: bool,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", google_vertex_ai)
    monkeypatch.setattr(
        settings,
        "GOOGLE_VERTEX_PROJECT",
        "vertex-project" if google_vertex_ai else None,
    )
    monkeypatch.setattr(settings, "GCP_PROJECT_ID", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    if not google_vertex_ai:
        monkeypatch.setattr(
            settings,
            "GOOGLE_API_KEY" if provider == "google" else "OPENAI_API_KEY",
            SecretStr("provider-test"),
        )

    response = await db_async_client.get("/api/v1/tools/catalog", headers=headers)

    assert response.status_code == 200
    entry = next(tool for tool in response.json()["tools"] if tool["name"] == "generate_image")
    assert entry["effect"] == "write"
    assert entry["effect_scope"] == "internal"
    assert entry["default_policy"] == "approval"
    assert entry["input_schema"]["required"] == ["prompt", "model_provider"]
    assert "input_image" not in entry["input_schema"]["properties"]
    tools = {tool["name"]: tool for tool in response.json()["tools"]}
    edit_entry = tools["edit_image"]
    assert edit_entry["input_schema"]["required"] == ["prompt", "file_ids"]
    assert edit_entry["input_schema"]["properties"]["file_ids"]["maxItems"] == 14
    if provider == "google":
        assert "generate_image_from_video" in tools
    else:
        assert "generate_image_from_video" not in tools


@pytest.mark.parametrize("role", [WorkspaceRole.ADMIN])
async def test_tool_availability_route_allows_workspace_managers(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    role: WorkspaceRole,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session, role=role)

    response = await db_async_client.put(
        "/api/v1/tools/web_search/availability",
        headers=headers,
        json={"enabled": False},
    )

    assert response.status_code == 200
    assert response.json() == {"tool_name": "web_search", "enabled": False}

    catalog_response = await db_async_client.get("/api/v1/tools/catalog", headers=headers)
    assert catalog_response.status_code == 200
    assert "web_search" not in {entry["name"] for entry in catalog_response.json()["tools"]}


@pytest.mark.parametrize("role", [WorkspaceRole.MEMBER])
async def test_tool_availability_route_rejects_non_managers(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    role: WorkspaceRole,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session, role=role)

    response = await db_async_client.put(
        "/api/v1/tools/web_search/availability",
        headers=headers,
        json={"enabled": False},
    )

    assert response.status_code == 403


async def test_tool_presentations_route_returns_every_first_party_runtime_tool(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session)

    response = await db_async_client.get("/api/v1/tools/presentations", headers=headers)

    assert response.status_code == 200
    body = response.json()
    names = [tool["name"] for tool in body["tools"]]
    assert names == sorted(names)
    assert "web_search" in names
    assert "write_file" in names  # non-configurable tools are included
    assert "delegate_to_agent" in names  # policy-injected tools are included
    assert "google_ads_get_report_field" in names
    assert "google_ads_list_report_fields" in names
    for entry in body["tools"]:
        if entry["name"].startswith("test_"):
            continue
        assert entry["ui"]["icon"] != "tool"
        assert entry["ui"]["running_label"]
        assert entry["ui"]["completed_label"]
        assert entry["ui"]["failed_label"]
        for field in (*entry["ui"]["arg_fields"], *entry["ui"]["result_fields"]):
            if not field["editable"]:
                assert field["placeholder"] == ""
                assert field["options"] == []


async def test_entity_reference_route_searches_and_hydrates_only_workspace_files(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    headers = {**headers, "X-Workspace": workspace.slug}
    agent = Agent(
        name="File agent",
        slug=f"file-agent-{uuid4().hex[:8]}",
        instructions="Work with files.",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    other_workspace = build_workspace(slug=f"other-files-{uuid4().hex[:8]}")
    db_session.add_all([agent, other_workspace])
    await db_session.flush()
    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        active_agent_id=agent.id,
    )
    db_session.add(conversation)
    await db_session.flush()
    current_file = build_file(workspace=workspace, name="Quarterly plan.pdf")
    other_file = build_file(workspace=other_workspace, name="Private roadmap.pdf")
    await set_session_tenant_context(db_session, workspace_id=other_workspace.id)
    db_session.add(other_file)
    await db_session.flush()
    await set_session_tenant_context(
        db_session,
        workspace_id=workspace.id,
        user_id=user.id,
    )
    db_session.add(current_file)
    await db_session.flush()
    await db_session.commit()

    endpoint = f"/api/v1/tools/conversations/{conversation.id}/entity-references"
    search = await db_async_client.post(
        endpoint,
        headers=headers,
        json={"tool_name": "read_file", "field_key": "file_id", "search": "Quarterly"},
    )

    assert search.status_code == 200, search.text
    assert [choice["label"] for choice in search.json()["choices"]] == ["Quarterly plan.pdf"]
    reference = search.json()["choices"][0]["value"]
    assert reference["entity_id"] == str(current_file.id)

    hydration = await db_async_client.post(
        endpoint,
        headers=headers,
        json={
            "tool_name": "read_file",
            "field_key": "file_id",
            "exact_values": [
                reference,
                {
                    **reference,
                    "entity_id": str(other_file.id),
                    "label": "Untrusted browser label",
                },
            ],
        },
    )

    assert hydration.status_code == 200
    assert [choice["value"]["entity_id"] for choice in hydration.json()["choices"]] == [
        str(current_file.id)
    ]
    assert hydration.json()["choices"][0]["label"] == "Quarterly plan.pdf"


async def test_entity_reference_route_requires_conversation_access(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    headers = {**headers, "X-Workspace": workspace.slug}
    other = build_user(email=f"other-tools-{uuid4().hex}@example.com")
    db_session.add(other)
    await db_session.flush()
    agent = Agent(
        name="Private agent",
        slug=f"private-agent-{uuid4().hex[:8]}",
        instructions="Private.",
        workspace_id=workspace.id,
        created_by=other.id,
    )
    db_session.add(agent)
    await db_session.flush()
    conversation = Conversation(
        user_id=other.id,
        workspace_id=workspace.id,
        created_by=other.id,
        active_agent_id=agent.id,
    )
    db_session.add(conversation)
    await db_session.commit()

    response = await db_async_client.post(
        f"/api/v1/tools/conversations/{conversation.id}/entity-references",
        headers=headers,
        json={"tool_name": "read_file", "field_key": "file_id", "search": ""},
    )

    assert response.status_code == 404
    assert user.id != other.id
