# apps/api/tests/routes/tools/test_tool_catalog_routes.py

"""HTTP-boundary tests for runtime tool catalog routes."""

from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
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
    web_search = next(tool for tool in body["tools"] if tool["name"] == "web_search")
    assert web_search == {
        "name": "web_search",
        "version": 1,
        "provider": "native",
        "label": "Web Search",
        "description": (
            "Search the web with a provider-native helper model. The helper model "
            "provider and model can be selected per call from the available native "
            "search providers: anthropic, google, openai."
        ),
        "kind": "function",
        "effect": "read",
        "effect_scope": "internal",
        "default_policy": "approval",
        "supported_policies": ["approval", "auto"],
        "defer_loading": False,
        "provider_keys": None,
        "resource_types": None,
        "input_schema": {
            "additionalProperties": False,
            "properties": {
                "query": {
                    "description": "Search query to send to the native-search helper model.",
                    "type": "string",
                },
                "model_provider": {
                    "anyOf": [
                        {
                            "enum": ["anthropic", "google", "openai"],
                            "type": "string",
                        },
                        {"type": "null"},
                    ],
                    "default": None,
                    "description": (
                        "Optional helper model provider. Omit unless there is a reason "
                        "to choose one. Available providers are anthropic, google, and "
                        "openai."
                    ),
                },
                "model": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": (
                        "Optional model id for model_provider. Omit to use that provider's "
                        "default native-search helper model."
                    ),
                },
            },
            "required": ["query"],
            "type": "object",
        },
    }
    assert "timeout" not in web_search
    assert "max_retries" not in web_search
    assert "output_model" not in web_search


async def test_tool_catalog_route_hides_web_search_without_provider_keys(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)

    response = await db_async_client.get("/api/v1/tools/catalog", headers=headers)

    assert response.status_code == 200
    assert "web_search" not in {tool["name"] for tool in response.json()["tools"]}


async def test_tool_catalog_route_requires_authentication(
    db_async_client: AsyncClient,
) -> None:
    response = await db_async_client.get("/api/v1/tools/catalog")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
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


@pytest.mark.parametrize("role", [WorkspaceRole.MEMBER, WorkspaceRole.READ_ONLY])
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


async def test_tool_availability_route_returns_not_found_for_unknown_tool(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.OWNER,
    )

    response = await db_async_client.put(
        "/api/v1/tools/not_a_runtime_tool/availability",
        headers=headers,
        json={"enabled": False},
    )

    assert response.status_code == 404


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
    write_file_entry = next(tool for tool in body["tools"] if tool["name"] == "write_file")
    assert write_file_entry["label"] == "Save File"
    assert write_file_entry["effect"] == "write"
    assert write_file_entry["ui"]["icon"] == "file-plus"
    assert write_file_entry["ui"]["running_label"] == "Saving {name}"
    assert write_file_entry["ui"]["approval_prompt"]
    assert write_file_entry["ui"]["approve_label"] == "Approve & Save"
    assert {field["key"] for field in write_file_entry["ui"]["arg_fields"]} == {
        "name",
        "file_id",
        "content",
    }
    write_file_fields = {field["key"]: field for field in write_file_entry["ui"]["arg_fields"]}
    assert write_file_fields["name"]["editable"] is True
    assert write_file_fields["file_id"]["format"] == "entity"
    assert write_file_fields["file_id"]["secondary"] is True
    assert write_file_fields["content"]["editable"] is False
    assert [field["key"] for field in write_file_entry["ui"]["result_fields"]] == [
        "name",
        "bytes_written",
    ]
    web_search_entry = next(tool for tool in body["tools"] if tool["name"] == "web_search")
    assert web_search_entry["ui"]["approve_label"] == "Approve & Search"
    assert web_search_entry["ui"]["arg_fields"] == [
        {
            "key": "query",
            "label": "Search",
            "format": "text",
            "editable": True,
            "placeholder": "What should the agent search for?",
            "options": [],
            "secondary": False,
            "entity_kind": None,
            "depends_on": [],
        },
        {
            "key": "model_provider",
            "label": "Search Provider",
            "format": "text",
            "editable": True,
            "placeholder": "",
            "options": ["anthropic", "google", "openai"],
            "secondary": False,
            "entity_kind": None,
            "depends_on": [],
        },
    ]
    assert all(field["editable"] is False for field in web_search_entry["ui"]["result_fields"])
    read_todos_entry = next(tool for tool in body["tools"] if tool["name"] == "read_todos")
    assert read_todos_entry["ui"]["icon"] == "list-todo"
    delegate_entry = next(tool for tool in body["tools"] if tool["name"] == "delegate_to_agent")
    assert delegate_entry["ui"]["approve_label"] == "Approve & Delegate"
    delegate_fields = {field["key"]: field for field in delegate_entry["ui"]["arg_fields"]}
    assert delegate_fields["agent_id"]["editable"] is True
    assert delegate_fields["agent_id"]["format"] == "entity"
    assert delegate_fields["task"]["editable"] is True
    assert delegate_fields["task"]["format"] == "multiline"
    save_memory_entry = next(tool for tool in body["tools"] if tool["name"] == "save_memory")
    save_memory_fields = {field["key"]: field for field in save_memory_entry["ui"]["arg_fields"]}
    assert save_memory_fields["kind"]["options"] == ["core", "note"]
    assert save_memory_fields["scope"]["options"] == ["agent", "user", "workspace"]
    assert save_memory_fields["title"]["editable"] is True
    assert save_memory_fields["content"]["editable"] is True
    assert save_memory_fields["importance"]["format"] == "number"
    assert save_memory_fields["importance"]["editable"] is True
    assert save_memory_fields["memory_type"]["options"] == [
        "fact",
        "preference",
        "episode",
        "outcome",
    ]
    assert save_memory_fields["expires_in_days"]["secondary"] is True


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
    db_session.add_all([current_file, other_file])
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


async def test_tool_presentations_route_requires_authentication(
    db_async_client: AsyncClient,
) -> None:
    response = await db_async_client.get("/api/v1/tools/presentations")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
