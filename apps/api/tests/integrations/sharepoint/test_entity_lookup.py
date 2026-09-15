"""Application lookup authorises SharePoint fields before provider access."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest

from core.auth.sessions import session_manager
from core.database import set_session_tenant_context
from integrations.sharepoint.references import SharePointDriveItemReference
from integrations.sharepoint.settings import sharepoint_settings
from models.agent import Agent
from models.agent_run import AgentRun
from tests.factories import (
    build_active_context_selection,
    build_conversation,
    build_external_credential,
    build_integration_connection,
    build_integration_resource,
    build_user,
    build_workspace,
    build_workspace_membership,
)
from tests.integrations.sharepoint.support import fixture, graph
from tests.support.auth import bearer_headers


@pytest.fixture
async def lookup_context(db_session, monkeypatch):
    actor = build_user()
    workspace = build_workspace()
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=actor.id)
    db_session.add_all([actor, workspace, membership])
    await db_session.flush()
    actor.default_workspace_id = workspace.id
    agent = Agent(
        name="Library agent",
        slug=f"library-agent-{uuid4().hex[:8]}",
        instructions="Find library folders.",
        workspace_id=workspace.id,
        created_by=actor.id,
        tool_names=["sharepoint_list_folder"],
    )
    db_session.add(agent)
    await db_session.flush()
    conversation = build_conversation(user=actor, workspace=workspace, active_agent_id=agent.id)
    credential = build_external_credential(provider_key="sharepoint")
    connection = build_integration_connection(
        credential=credential, user=actor, workspace=workspace, status="active"
    )
    resource = build_integration_resource(
        connection=connection,
        resource_type="sharepoint_drive",
        external_id="drive",
        display_name="Documents",
        enabled=True,
    )
    db_session.add_all([conversation, credential, connection, resource])
    await db_session.flush()
    run = AgentRun(
        conversation_id=conversation.id,
        workspace_id=workspace.id,
        agent_id=agent.id,
        user_id=actor.id,
        trigger="interactive",
        status="completed",
    )
    selection = build_active_context_selection(
        workspace=workspace, conversation=conversation, resource=resource
    )
    db_session.add_all([run, selection])
    session = await session_manager.create_session(db_session, str(actor.id))
    await db_session.commit()
    monkeypatch.setattr(sharepoint_settings, "SHAREPOINT_OAUTH_CLIENT_ID", "configured")
    return SimpleNamespace(
        actor=actor,
        workspace=workspace,
        agent=agent,
        conversation=conversation,
        resource=resource,
        connection=connection,
        credential=credential,
        selection=selection,
        headers={**bearer_headers(session["session_token"]), "X-Workspace": workspace.slug},
        endpoint=f"/api/v1/tools/conversations/{conversation.id}/entity-references",
    )


@pytest.mark.parametrize("search", ["Report", ""])
async def test_lookup_route_searches_selected_drive_with_acting_user(
    db_async_client, lookup_context, monkeypatch, search
):
    ctx = lookup_context
    file, folder = fixture("children.json")["value"]
    requests = []

    def handler(request):
        requests.append(request)
        expected = "search(q='Report')" if search else "children"
        assert request.url.path == f"/v1.0/drives/drive/root/{expected}"
        return httpx2.Response(200, json={"value": [file, {**folder, "name": "Reports"}]})

    async with graph(handler) as provider:
        client = AsyncMock(return_value=provider)
        monkeypatch.setattr(
            "integrations.sharepoint.entity_resolvers.drive_item.drive_client_for_principal", client
        )
        response = await db_async_client.post(
            ctx.endpoint,
            headers=ctx.headers,
            json={"tool_name": "sharepoint_list_folder", "field_key": "folder", "search": search},
        )
    assert response.status_code == 200, response.text
    choices = response.json()["choices"]
    assert len(choices) == 2 and len(requests) == 1
    for choice in choices:
        reference = SharePointDriveItemReference.model_validate(choice["value"])
        assert choice["identity"] == list(reference.identity())
        assert reference.drive_id == "drive"
        assert reference.label == reference.name == choice["label"]
        assert reference.scope_label == choice["scope_label"] == "Documents"
    assert {choice["description"] for choice in choices} == {
        "Folder",
        "File; choose a folder to list its contents.",
    }
    client.assert_awaited_once()
    principal = client.await_args.kwargs
    assert principal["actor"].id == ctx.actor.id
    assert principal["workspace"].id == ctx.workspace.id
    assert principal["entry"].integration_resource_id == ctx.resource.id


@pytest.mark.parametrize("count", [25, 26])
async def test_lookup_route_enforces_exact_limit_before_credentials(
    db_async_client, lookup_context, monkeypatch, count
):
    ctx = lookup_context
    requests = []
    file = fixture("children.json")["value"][0]
    values = [
        SharePointDriveItemReference(
            drive_id="drive", item_id=f"item-{i}", label="Stale"
        ).model_dump()
        for i in range(count)
    ]

    def handler(request):
        requests.append(request)
        item_id = request.url.path.rsplit("/", 1)[-1]
        return httpx2.Response(200, json={**file, "id": item_id})

    async with graph(handler) as provider:
        client = AsyncMock(return_value=provider)
        monkeypatch.setattr(
            "integrations.sharepoint.entity_resolvers.drive_item.drive_client_for_principal", client
        )
        response = await db_async_client.post(
            ctx.endpoint,
            headers=ctx.headers,
            json={
                "tool_name": "sharepoint_list_folder",
                "field_key": "folder",
                "exact_values": values,
            },
        )
    if count == 26:
        assert response.status_code == 400, response.text
        assert "at most 25" in response.text
        client.assert_not_awaited()
        assert requests == []
    else:
        assert response.status_code == 200, response.text
        assert len(requests) == client.await_count == 25
        choices = response.json()["choices"]
        assert [choice["value"]["item_id"] for choice in choices] == [
            value["item_id"] for value in values
        ]
        assert all(choice["label"] == file["name"] for choice in choices)


@pytest.mark.parametrize(
    "boundary",
    [
        "unmounted",
        "unconfigured",
        "incompatible",
        "private_conversation",
        "other_actor_connection",
        "wrong_field",
    ],
)
async def test_lookup_route_rejects_unauthorised_fields_before_credentials(
    db_session, db_async_client, lookup_context, monkeypatch, boundary
):
    ctx = lookup_context
    field = "folder"
    if boundary == "unmounted":
        ctx.agent.tool_names = []
    elif boundary == "unconfigured":
        monkeypatch.setattr(sharepoint_settings, "SHAREPOINT_OAUTH_CLIENT_ID", "")
    elif boundary == "incompatible":
        ctx.resource.resource_type = "outlook_mailbox"
    elif boundary in {"private_conversation", "other_actor_connection"}:
        other = build_user(email=f"other-{uuid4().hex}@example.com")
        db_session.add(other)
        await db_session.flush()
        if boundary == "private_conversation":
            ctx.conversation.user_id = other.id
            ctx.conversation.created_by = other.id
        else:
            await set_session_tenant_context(
                db_session, workspace_id=ctx.workspace.id, user_id=other.id
            )
            credential = build_external_credential(provider_key="sharepoint")
            connection = build_integration_connection(
                credential=credential, user=other, owner_user_id=other.id, status="active"
            )
            resource = build_integration_resource(
                connection=connection,
                resource_type="sharepoint_drive",
                external_id="private-drive",
                enabled=True,
            )
            db_session.add_all([credential, connection, resource])
            await db_session.flush()
            await set_session_tenant_context(
                db_session, workspace_id=ctx.workspace.id, user_id=ctx.actor.id
            )
            ctx.selection.integration_resource_id = resource.id
    else:
        field = "limit"
    await db_session.commit()
    client = AsyncMock(side_effect=AssertionError("Unexpected credential access"))
    monkeypatch.setattr(
        "integrations.sharepoint.entity_resolvers.drive_item.drive_client_for_principal", client
    )
    response = await db_async_client.post(
        ctx.endpoint,
        headers=ctx.headers,
        json={"tool_name": "sharepoint_list_folder", "field_key": field, "search": "Report"},
    )
    assert response.status_code == (404 if boundary == "private_conversation" else 400), (
        response.text
    )
    if boundary != "private_conversation":
        assert response.json()["detail"] == (
            "Tool field is not an entity reference"
            if boundary == "wrong_field"
            else "Tool is not available in this conversation"
        )
    client.assert_not_awaited()
