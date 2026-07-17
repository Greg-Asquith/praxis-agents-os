# apps/api/tests/routes/tools/test_tool_cataloy_routes.py

"""HTTP-boundary tests for runtime tool catalog routes."""

from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from tests.factories import build_user, build_workspace, build_workspace_membership
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
    assert body["tools"] == [
        {
            "name": "web_search",
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
        },
    ]
    assert "timeout" not in body["tools"][0]
    assert "max_retries" not in body["tools"][0]
    assert "output_model" not in body["tools"][0]


async def test_tool_catalog_route_requires_authentication(
    db_async_client: AsyncClient,
) -> None:
    response = await db_async_client.get("/api/v1/tools/catalog")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_tool_presentations_route_returns_every_registry_tool(
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
    for entry in body["tools"]:
        if entry["name"] == "web_search":
            continue
        assert entry["ui"]["approve_label"] == ""
        for field in (*entry["ui"]["arg_fields"], *entry["ui"]["result_fields"]):
            assert field["placeholder"] == ""
            assert field["options"] == []
            assert field["secondary"] is False
    write_file_entry = next(tool for tool in body["tools"] if tool["name"] == "write_file")
    assert write_file_entry["label"] == "Write file"
    assert write_file_entry["effect"] == "write"
    assert write_file_entry["ui"]["icon"] == "file-plus"
    assert write_file_entry["ui"]["running_label"] == "Writing {name}"
    assert write_file_entry["ui"]["approval_prompt"]
    assert {field["key"] for field in write_file_entry["ui"]["arg_fields"]} == {"name", "content"}
    assert all(field["editable"] is False for field in write_file_entry["ui"]["arg_fields"])
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
        },
        {
            "key": "model_provider",
            "label": "Search provider",
            "format": "text",
            "editable": False,
            "placeholder": "",
            "options": [],
            "secondary": False,
        },
    ]
    assert all(field["editable"] is False for field in web_search_entry["ui"]["result_fields"])
    read_todos_entry = next(tool for tool in body["tools"] if tool["name"] == "read_todos")
    assert read_todos_entry["ui"]["icon"] == "list-todo"


async def test_tool_presentations_route_requires_authentication(
    db_async_client: AsyncClient,
) -> None:
    response = await db_async_client.get("/api/v1/tools/presentations")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
