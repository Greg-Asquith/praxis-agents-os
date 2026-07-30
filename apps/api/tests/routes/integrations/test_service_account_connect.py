# apps/api/tests/routes/integrations/test_service_account_connect.py

"""Security and RBAC tests for service-account connection intake."""

import json

import pytest
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit_event import AuditEvent
from models.integrations import ExternalCredential, IntegrationConnection
from models.workspace import WorkspaceRole
from tests.routes.integrations.conftest import create_identity


@pytest.mark.parametrize("provider_key", ["google_ads", "bigquery"])
async def test_service_account_is_persisted_by_reference_only(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    caplog,
    provider_key: str,
) -> None:
    private_key = "private-key-never-persist-this-value"
    raw = json.dumps(
        {
            "type": "service_account",
            "project_id": "praxis-analytics",
            "client_email": "agent@example.iam.gserviceaccount.com",
            "private_key": private_key,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )
    response = await db_async_client.post(
        "/api/v1/integrations/connections/service-account",
        headers=integration_identity["headers"],
        json={
            "provider_key": provider_key,
            "label": "Agency Data",
            "service_account_json": raw,
        },
    )
    assert response.status_code == 200, response.text
    assert private_key not in response.text

    connection = await db_session.get(IntegrationConnection, response.json()["id"])
    assert connection is not None
    assert connection.owner_workspace_id == integration_identity["workspace"].id
    assert connection.status == "discovery_pending"
    assert connection.provider_metadata == {
        "service_account_email": "agent@example.iam.gserviceaccount.com"
    }
    credential = await db_session.get(ExternalCredential, connection.credential_id)
    assert credential is not None
    assert credential.auth_mode == "service_account"
    assert credential.access_token_encrypted is None
    assert credential.refresh_token_encrypted is None
    assert credential.secret_name
    serialized_audits = json.dumps(
        [event.details for event in (await db_session.scalars(select(AuditEvent))).all()]
    )
    assert private_key not in serialized_audits
    assert private_key not in caplog.text


async def test_service_account_rejects_missing_client_email(
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    response = await db_async_client.post(
        "/api/v1/integrations/connections/service-account",
        headers=integration_identity["headers"],
        json={
            "provider_key": "google_ads",
            "label": "Invalid",
            "service_account_json": json.dumps({"private_key": "hidden"}),
        },
    )
    assert response.status_code == 400
    assert "hidden" not in response.text


async def test_service_account_rejects_another_workspaces_secret_reference(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    foreign_email = "foreign@example.iam.gserviceaccount.com"
    initial = await db_async_client.post(
        "/api/v1/integrations/connections/service-account",
        headers=integration_identity["headers"],
        json={
            "provider_key": "google_ads",
            "label": "First workspace",
            "service_account_json": json.dumps(
                {
                    "type": "service_account",
                    "project_id": "foreign-project",
                    "client_email": foreign_email,
                    "private_key": "foreign-private-key",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            ),
        },
    )
    assert initial.status_code == 200, initial.text
    connection = await db_session.get(IntegrationConnection, initial.json()["id"])
    credential = await db_session.get(ExternalCredential, connection.credential_id)

    _user, _workspace, _membership, other_headers = await create_identity(
        db_session,
        role=WorkspaceRole.OWNER,
    )
    response = await db_async_client.post(
        "/api/v1/integrations/connections/service-account",
        headers=other_headers,
        json={
            "provider_key": "google_ads",
            "label": "Cross-workspace reference",
            "secret_reference": {
                "provider": credential.secret_provider,
                "name": credential.secret_name,
                "version": credential.secret_version,
            },
        },
    )

    assert response.status_code == 400
    assert "not authorized for this workspace" in response.text
    assert foreign_email not in response.text


async def test_member_cannot_connect_workspace_service_account(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    _user, _workspace, _membership, headers = await create_identity(
        db_session,
        role=WorkspaceRole.MEMBER,
        workspace=integration_identity["workspace"],
    )
    response = await db_async_client.post(
        "/api/v1/integrations/connections/service-account",
        headers=headers,
        json={
            "provider_key": "google_ads",
            "label": "Denied",
            "service_account_json": json.dumps(
                {
                    "client_email": "agent@example.iam.gserviceaccount.com",
                    "private_key": "hidden",
                }
            ),
        },
    )
    assert response.status_code == 403
