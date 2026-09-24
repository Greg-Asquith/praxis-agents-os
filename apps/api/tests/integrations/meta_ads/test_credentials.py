"""Checks secret resolution and credential revocation before requests."""

import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from pydantic import SecretStr
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationAuthError
from integrations.meta_ads.settings import meta_ads_settings
from integrations.meta_ads.tools.utils.client import meta_ads_client, meta_ads_client_for_principal
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.http import IntegrationRequestPolicy
from tests.integrations.meta_ads.support import TOKEN, DiscoveryTransport, install_transport


@pytest.fixture
def credential_context(monkeypatch):
    actor = SimpleNamespace(id=uuid4())
    workspace = SimpleNamespace(id=uuid4())
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="meta_ads",
        resource_type="meta_ads_ad_account",
        external_id="123",
        display_name="Account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=True,
    )
    credential = SimpleNamespace(
        auth_mode="api_key",
        secret_provider="local",  # noqa: S106 - inert secret reference
        secret_name="workspace-meta-token",  # noqa: S106 - inert secret reference
        secret_version="1",  # noqa: S106 - inert secret reference
    )
    usable = AsyncMock(return_value=credential)
    resolve = AsyncMock(return_value=TOKEN)
    monkeypatch.setattr(
        "integrations.meta_ads.tools.utils.client.get_usable_connection_credential", usable
    )
    monkeypatch.setattr("integrations.meta_ads.tools.utils.client.resolve_secret", resolve)
    monkeypatch.setattr(meta_ads_settings, "META_ADS_APP_SECRET", SecretStr("app-secret"))
    return SimpleNamespace(
        db=object(),
        actor=actor,
        workspace=workspace,
        entry=entry,
        credential=credential,
        usable=usable,
        resolve=resolve,
    )


@pytest.mark.parametrize("runtime_context", [False, True])
async def test_api_key_client_resolves_scoped_secret_and_deployment_proof(
    monkeypatch, credential_context, runtime_context
) -> None:
    context = credential_context
    transport = DiscoveryTransport()
    install_transport(monkeypatch, transport)
    if runtime_context:
        client = await meta_ads_client(
            SimpleNamespace(
                deps=SimpleNamespace(db=context.db, user=context.actor, workspace=context.workspace)
            ),
            context.entry,
        )
    else:
        client = await meta_ads_client_for_principal(
            context.db, actor=context.actor, workspace=context.workspace, entry=context.entry
        )
    await client.graph_get("me", operation="identity", policy=IntegrationRequestPolicy.READ)

    context.usable.assert_awaited_once_with(
        context.db,
        connection_id=context.entry.connection_id,
        actor=context.actor,
        workspace=context.workspace,
    )
    secret_call = context.resolve.await_args
    assert secret_call.args[1].name == "workspace-meta-token"
    assert secret_call.kwargs == {
        "workspace_id": context.workspace.id,
        "actor_id": context.actor.id,
    }
    request = transport.requests[0]
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert (
        request.url.params["appsecret_proof"]
        == hmac.new(b"app-secret", TOKEN.encode(), hashlib.sha256).hexdigest()
    )


async def test_revoked_credential_is_rechecked_before_every_request(
    monkeypatch, credential_context
) -> None:
    context = credential_context
    transport = DiscoveryTransport()
    install_transport(monkeypatch, transport)
    client = await meta_ads_client_for_principal(
        context.db, actor=context.actor, workspace=context.workspace, entry=context.entry
    )
    await client.graph_get("me", operation="identity", policy=IntegrationRequestPolicy.READ)
    context.usable.side_effect = IntegrationAuthError("Connection revoked", provider_key="meta_ads")

    with pytest.raises(IntegrationAuthError, match="revoked"):
        await client.graph_get("me", operation="identity", policy=IntegrationRequestPolicy.READ)
    assert len(transport.requests) == 1
    assert context.resolve.await_count == 1


@pytest.mark.parametrize("invalid", ["auth_mode", "empty_secret"])
async def test_unusable_credentials_fail_before_transport(
    monkeypatch, credential_context, invalid
) -> None:
    context = credential_context
    if invalid == "auth_mode":
        context.credential.auth_mode = "oauth"
    else:
        context.resolve.return_value = "  "
    request = AsyncMock()
    monkeypatch.setattr(httpx2.AsyncClient, "request", request)
    client = await meta_ads_client_for_principal(
        context.db, actor=context.actor, workspace=context.workspace, entry=context.entry
    )
    with pytest.raises(ModelRetry, match="reconnect"):
        await client.graph_get("me", operation="identity", policy=IntegrationRequestPolicy.READ)
    request.assert_not_awaited()
