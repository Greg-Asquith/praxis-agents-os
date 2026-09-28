# apps/api/tests/routes/integrations/test_context_routes.py

"""Active-context and context-group route contracts."""

from uuid import uuid4

from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
