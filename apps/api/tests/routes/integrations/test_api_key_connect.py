"""Security and RBAC tests for API-key connection intake."""

import json
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit_event import AuditEvent
from models.integrations import ExternalCredential, IntegrationConnection
from models.workspace import WorkspaceRole
from services.integrations.connections.schemas import ApiKeyConnectRequest
from services.secrets.domain import SecretReference
from tests.routes.integrations.conftest import create_identity

pytestmark = pytest.mark.asyncio


async def test_blank_api_key_is_rejected_before_storage() -> None:
    with pytest.raises(ValidationError):
        ApiKeyConnectRequest(provider_key="airtable", label="Blank", api_key="   ")


async def test_new_secret_is_deleted_when_connection_persistence_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = import_module("services.integrations.connections.connect_api_key")
    reference = SecretReference(provider="local", name="temporary-secret", version="1")
    deleted: list[SecretReference] = []

    async def write_secret(*args, **kwargs):
        return reference

    async def fail_store(*args, **kwargs):
        raise RuntimeError("database write failed")

    async def delete_secret(db, ref, **kwargs):
        deleted.append(ref)
        return True

    monkeypatch.setattr(module, "write_secret", write_secret)
    monkeypatch.setattr(module, "store_secret_reference_credential", fail_store)
    monkeypatch.setattr(module, "delete_secret", delete_secret)

    with pytest.raises(RuntimeError, match="database write failed"):
        await module.connect_api_key(
            object(),
            actor=SimpleNamespace(id=uuid4()),
            workspace=SimpleNamespace(id=uuid4()),
            payload=ApiKeyConnectRequest(
                provider_key="airtable",
                label="Compensated",
                api_key="secret-value",
            ),
        )

    assert deleted == [reference]


async def test_raw_api_key_is_replaced_by_reference_everywhere(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_key = "pat-never-persist-this-value"
    response = await db_async_client.post(
        "/api/v1/integrations/connections/api-key",
        headers=integration_identity["headers"],
        json={"provider_key": "airtable", "label": "Production", "api_key": raw_key},
    )
    assert response.status_code == 200, response.text
    assert raw_key not in response.text
    assert response.json()["credential"]["secret_reference"].startswith("local:")

    connection = await db_session.get(IntegrationConnection, response.json()["id"])
    assert connection is not None and connection.status == "active"
    credential = await db_session.get(ExternalCredential, connection.credential_id)
    assert credential is not None
    assert credential.auth_mode == "api_key"
    assert credential.access_token_encrypted is None
    assert credential.refresh_token_encrypted is None
    assert credential.secret_provider == "local"
    assert credential.secret_name in response.json()["credential"]["secret_reference"]
    serialized_audits = json.dumps(
        [event.details for event in (await db_session.scalars(select(AuditEvent))).all()]
    )
    assert raw_key not in serialized_audits
    assert raw_key not in caplog.text


async def test_member_cannot_enter_api_key(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    workspace = integration_identity["workspace"]
    _user, _workspace, _membership, headers = await create_identity(
        db_session,
        role=WorkspaceRole.MEMBER,
        workspace=workspace,
    )
    response = await db_async_client.post(
        "/api/v1/integrations/connections/api-key",
        headers=headers,
        json={"provider_key": "airtable", "label": "Denied", "api_key": "secret"},
    )
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_reference_only_connect_validates_and_accepts_existing_secret(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    initial = await db_async_client.post(
        "/api/v1/integrations/connections/api-key",
        headers=integration_identity["headers"],
        json={"provider_key": "airtable", "label": "Initial", "api_key": "first-value"},
    )
    assert initial.status_code == 200
    connection = await db_session.get(IntegrationConnection, initial.json()["id"])
    credential = await db_session.get(ExternalCredential, connection.credential_id)

    response = await db_async_client.post(
        "/api/v1/integrations/connections/api-key",
        headers=integration_identity["headers"],
        json={
            "provider_key": "airtable",
            "label": "Reference reuse",
            "secret_reference": {
                "provider": credential.secret_provider,
                "name": credential.secret_name,
                "version": credential.secret_version,
            },
        },
    )
    assert response.status_code == 200, response.text

    malformed = await db_async_client.post(
        "/api/v1/integrations/connections/api-key",
        headers=integration_identity["headers"],
        json={
            "provider_key": "airtable",
            "label": "Malformed",
            "secret_reference": {"provider": "local", "name": "../bad", "version": "1"},
        },
    )
    assert malformed.status_code == 400
