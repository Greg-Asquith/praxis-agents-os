# apps/api/tests/routes/integrations/test_context_routes.py

"""Active-context and context-group route contracts."""

from uuid import uuid4

from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import IntegrationConnection
from models.workspace import WorkspaceRole
from tests.factories import (
    build_conversation,
    build_external_credential,
    build_integration_connection,
    build_integration_resource,
)
from tests.routes.integrations.conftest import create_identity


async def _workspace_resource(db: AsyncSession, identity: dict[str, object]):
    conversation = build_conversation(user=identity["user"], workspace=identity["workspace"])
    credential = build_external_credential(principal_fingerprint=uuid4().hex.ljust(64, "0"))
    db.add_all([conversation, credential])
    await db.flush()
    connection = build_integration_connection(
        credential=credential,
        user=identity["user"],
        workspace=identity["workspace"],
        status="active",
    )
    db.add(connection)
    await db.flush()
    resource = build_integration_resource(
        connection=connection,
        enabled=True,
        writable=True,
        permissions_metadata={"role": "editor", "provider_secret": "internal-only"},
    )
    db.add(resource)
    await db.commit()
    return conversation, resource


async def test_context_routes_round_trip_selection_and_group(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    conversation, resource = await _workspace_resource(db_session, integration_identity)
    created = await db_async_client.post(
        "/api/v1/integrations/context-groups",
        headers=integration_identity["headers"],
        json={"name": "Client accounts", "resource_ids": [str(resource.id)]},
    )
    assert created.status_code == 201, created.text
    group = created.json()
    assert group["name"] == "Client accounts"
    assert [member["id"] for member in group["members"]] == [str(resource.id)]

    selected = await db_async_client.put(
        f"/api/v1/integrations/conversations/{conversation.id}/context",
        headers=integration_identity["headers"],
        json={
            "targets": [
                {"type": "context_group", "context_group_id": group["id"]},
                {"type": "resource", "integration_resource_id": str(resource.id)},
            ]
        },
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["targets"] == [
        {"type": "context_group", "context_group_id": group["id"]},
        {"type": "resource", "integration_resource_id": str(resource.id)},
    ]
    assert selected.json()["entries"] == [
        {
            "integration_resource_id": str(resource.id),
            "provider_key": "test_provider",
            "resource_type": "test_resource",
            "external_id": "resource-1",
            "display_name": "Test resource",
            "connection_id": str(resource.connection_id),
            "connection_label": "Test connection",
            "connection_status": "active",
            "write_allowed": True,
            "is_personal": False,
        }
    ]
    assert selected.json()["unavailable"] == []
    assert "permissions_metadata" not in selected.text
    other_conversation = build_conversation(
        user=integration_identity["user"],
        workspace=integration_identity["workspace"],
        title="Context B conversation",
    )
    db_session.add(other_conversation)
    await db_session.commit()
    other_selected = await db_async_client.put(
        f"/api/v1/integrations/conversations/{other_conversation.id}/context",
        headers=integration_identity["headers"],
        json={"targets": [{"type": "resource", "integration_resource_id": str(resource.id)}]},
    )
    assert other_selected.status_code == 200, other_selected.text
    fetched = await db_async_client.get(
        f"/api/v1/integrations/conversations/{conversation.id}/context",
        headers=integration_identity["headers"],
    )
    assert fetched.status_code == 200
    assert fetched.json() == selected.json()
    other_fetched = await db_async_client.get(
        f"/api/v1/integrations/conversations/{other_conversation.id}/context",
        headers=integration_identity["headers"],
    )
    assert other_fetched.status_code == 200
    assert other_fetched.json() == other_selected.json()

    emptied = await db_async_client.put(
        f"/api/v1/integrations/conversations/{conversation.id}/context",
        headers=integration_identity["headers"],
        json={"targets": []},
    )
    assert emptied.status_code == 200
    assert emptied.json() == {"targets": [], "entries": [], "unavailable": []}

    cleared = await db_async_client.delete(
        f"/api/v1/integrations/conversations/{conversation.id}/context",
        headers=integration_identity["headers"],
    )
    assert cleared.status_code == 204


async def test_context_route_safely_reports_degraded_saved_targets(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    conversation, resource = await _workspace_resource(db_session, integration_identity)
    selected = await db_async_client.put(
        f"/api/v1/integrations/conversations/{conversation.id}/context",
        headers=integration_identity["headers"],
        json={"targets": [{"type": "resource", "integration_resource_id": str(resource.id)}]},
    )
    assert selected.status_code == 200, selected.text
    assert [entry["integration_resource_id"] for entry in selected.json()["entries"]] == [
        str(resource.id)
    ]

    resource.enabled = False
    await db_session.commit()
    disabled = await db_async_client.get(
        f"/api/v1/integrations/conversations/{conversation.id}/context",
        headers=integration_identity["headers"],
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["entries"] == []
    assert disabled.json()["unavailable"] == [
        {
            "display_name": "Test resource",
            "provider_key": "test_provider",
            "reason": "resource_disabled",
        }
    ]

    resource.enabled = True
    connection = await db_session.get(IntegrationConnection, resource.connection_id)
    assert connection is not None
    connection.status = "revoked"
    await db_session.commit()
    revoked = await db_async_client.get(
        f"/api/v1/integrations/conversations/{conversation.id}/context",
        headers=integration_identity["headers"],
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["entries"] == []
    assert revoked.json()["unavailable"] == [
        {
            "display_name": "Test resource",
            "provider_key": "test_provider",
            "reason": "connection_revoked",
        }
    ]

    created_group = await db_async_client.post(
        "/api/v1/integrations/context-groups",
        headers=integration_identity["headers"],
        json={"name": "Temporary context", "resource_ids": []},
    )
    assert created_group.status_code == 201, created_group.text
    group_id = created_group.json()["id"]
    selected_group = await db_async_client.put(
        f"/api/v1/integrations/conversations/{conversation.id}/context",
        headers=integration_identity["headers"],
        json={"targets": [{"type": "context_group", "context_group_id": group_id}]},
    )
    assert selected_group.status_code == 200, selected_group.text
    deleted_group = await db_async_client.delete(
        f"/api/v1/integrations/context-groups/{group_id}",
        headers=integration_identity["headers"],
    )
    assert deleted_group.status_code == 204, deleted_group.text
    dangling = await db_async_client.get(
        f"/api/v1/integrations/conversations/{conversation.id}/context",
        headers=integration_identity["headers"],
    )
    assert dangling.status_code == 200, dangling.text
    assert dangling.json()["entries"] == []
    assert dangling.json()["unavailable"] == [
        {
            "display_name": "Selected context",
            "provider_key": "unknown",
            "reason": "dangling",
        }
    ]


async def test_context_route_allows_read_only_member_to_manage_own_selection(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    owner_conversation, resource = await _workspace_resource(db_session, integration_identity)
    reader, workspace, _membership, headers = await create_identity(
        db_session,
        role=WorkspaceRole.READ_ONLY,
        workspace=integration_identity["workspace"],
    )
    hidden = await db_async_client.get(
        f"/api/v1/integrations/conversations/{owner_conversation.id}/context",
        headers=headers,
    )
    assert hidden.status_code == 404
    reader_conversation = build_conversation(user=reader, workspace=workspace)
    db_session.add(reader_conversation)
    await db_session.commit()
    read = await db_async_client.get(
        f"/api/v1/integrations/conversations/{reader_conversation.id}/context",
        headers=headers,
    )
    assert read.status_code == 200
    selected = await db_async_client.put(
        f"/api/v1/integrations/conversations/{reader_conversation.id}/context",
        headers=headers,
        json={"targets": [{"type": "resource", "integration_resource_id": str(resource.id)}]},
    )
    assert selected.status_code == 200
    cleared = await db_async_client.delete(
        f"/api/v1/integrations/conversations/{reader_conversation.id}/context",
        headers=headers,
    )
    assert cleared.status_code == 204


async def test_context_route_hides_cross_workspace_resource(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    foreign_user, foreign_workspace, _membership, _headers = await create_identity(
        db_session,
        role=WorkspaceRole.OWNER,
    )
    foreign_identity = {"user": foreign_user, "workspace": foreign_workspace}
    _foreign_conversation, foreign_resource = await _workspace_resource(
        db_session, foreign_identity
    )
    conversation = build_conversation(
        user=integration_identity["user"],
        workspace=integration_identity["workspace"],
    )
    db_session.add(conversation)
    await db_session.commit()
    response = await db_async_client.put(
        f"/api/v1/integrations/conversations/{conversation.id}/context",
        headers=integration_identity["headers"],
        json={
            "targets": [
                {
                    "type": "resource",
                    "integration_resource_id": str(foreign_resource.id),
                }
            ]
        },
    )
    assert response.status_code == 404, response.text


async def test_shared_context_group_route_rejects_user_owned_resource(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    credential = build_external_credential(principal_fingerprint=uuid4().hex.ljust(64, "0"))
    db_session.add(credential)
    await db_session.flush()
    connection = build_integration_connection(
        credential=credential,
        user=integration_identity["user"],
        owner_user_id=integration_identity["user"].id,
        status="active",
    )
    db_session.add(connection)
    await db_session.flush()
    resource = build_integration_resource(connection=connection, enabled=True)
    db_session.add(resource)
    await db_session.commit()

    response = await db_async_client.post(
        "/api/v1/integrations/context-groups",
        headers=integration_identity["headers"],
        json={"name": "Personal inbox", "resource_ids": [str(resource.id)]},
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "https://httpstatuses.com/400",
        "title": "Validation Error",
        "status": 400,
        "detail": "Resources must be available to Context Groups in the current workspace",
        "field": "resource_ids",
    }
