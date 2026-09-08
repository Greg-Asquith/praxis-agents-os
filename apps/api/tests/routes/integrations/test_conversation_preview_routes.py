# apps/api/tests/routes/integrations/test_conversation_preview_routes.py

"""Conversation preview authorisation and provider boundaries."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from core.database import set_session_tenant_context
from integrations.outlook_mail import PROVIDER
from models.workspace import WorkspaceRole
from services.integrations.manifest import PROVIDER_MANIFESTS
from services.integrations.plugin import PROVIDER_PLUGINS
from tests.factories import (
    build_active_context_selection,
    build_conversation,
    build_external_credential,
    build_integration_connection,
    build_integration_resource,
)
from tests.routes.integrations.conftest import create_identity


@pytest.fixture(autouse=True)
def outlook_preview_provider(monkeypatch):
    monkeypatch.setitem(PROVIDER_PLUGINS, "outlook_mail", PROVIDER)
    monkeypatch.setitem(PROVIDER_MANIFESTS, "outlook_mail", PROVIDER.manifest)


async def preview_context(db, identity, *, count=1, provider="outlook_mail", owner=None):
    user, workspace = identity["user"], identity["workspace"]
    conversation = build_conversation(user=user, workspace=workspace)
    db.add(conversation)
    await db.flush()
    for _ in range(count):
        mailbox_owner = owner or user
        await set_session_tenant_context(db, workspace_id=workspace.id, user_id=mailbox_owner.id)
        credential = build_external_credential(
            provider_key=provider, principal_fingerprint=uuid4().hex * 2
        )
        connection = build_integration_connection(
            credential=credential,
            user=mailbox_owner,
            owner_user_id=mailbox_owner.id,
            status="active",
        )
        resource = build_integration_resource(
            connection=connection,
            resource_type="outlook_mailbox" if provider == "outlook_mail" else "gmail_mailbox",
            enabled=True,
            external_id="mailbox",
        )
        db.add_all([credential, connection, resource])
        await db.flush()
        await set_session_tenant_context(db, workspace_id=workspace.id, user_id=user.id)
        db.add(
            build_active_context_selection(
                workspace=workspace, conversation=conversation, resource=resource
            )
        )
    await db.commit()
    return conversation


def preview_url(conversation, kind="outlook_message"):
    return f"/api/v1/integrations/conversations/{conversation.id}/previews/{kind}"


async def test_conversation_outlook_preview_encodes_id_sanitizes_and_closes_transaction(
    db_session, db_async_client, integration_identity, monkeypatch
):
    from integrations.outlook_mail.operations import preview_message

    conversation = await preview_context(db_session, integration_identity)
    get = AsyncMock(
        return_value={
            "subject": "Invoice",
            "body": {
                "contentType": "html",
                "content": '<p>Invoice</p><script>private()</script><img onerror="bad()" src="x">',
            },
        }
    )
    from types import SimpleNamespace

    def client(db, _connection, **_kwargs):
        assert not db.in_transaction()
        return SimpleNamespace(get=get)

    monkeypatch.setattr(preview_message, "graph_client_for_connection", client)
    reference = "A" * 180 + "+/=="
    response = await db_async_client.get(
        preview_url(conversation),
        params={"provider_key": "outlook_mail", "scope_id": "mailbox", "ref": reference},
        headers=integration_identity["headers"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["meta"]["subject"] == "Invoice"
    assert "<script" not in response.json()["content"]
    assert "onerror" not in response.json()["content"]
    assert get.call_args.args[0].endswith("%2B%2F%3D%3D")


@pytest.mark.parametrize(
    "case",
    [
        "empty",
        "no_match",
        "ambiguous",
        "other_personal",
        "other_conversation",
        "other_actor",
        "other_workspace",
    ],
)
async def test_conversation_preview_denies_unavailable_targets_without_provider_io(
    db_session, db_async_client, integration_identity, monkeypatch, case
):
    from integrations.outlook_mail.operations import preview_message

    owner = None
    headers = integration_identity["headers"]
    if case in {"other_personal", "other_actor", "other_workspace"}:
        owner, _, _, other_headers = await create_identity(
            db_session,
            role=WorkspaceRole.OWNER,
            workspace=integration_identity["workspace"] if case != "other_workspace" else None,
        )
        await set_session_tenant_context(
            db_session,
            workspace_id=integration_identity["workspace"].id,
            user_id=integration_identity["user"].id,
        )
        if case != "other_personal":
            headers = other_headers
    conversation = await preview_context(
        db_session,
        integration_identity,
        count=0 if case == "empty" else 2 if case == "ambiguous" else 1,
        owner=owner if case == "other_personal" else None,
    )
    if case == "other_conversation":
        conversation = build_conversation(
            user=integration_identity["user"], workspace=integration_identity["workspace"]
        )
        db_session.add(conversation)
        await db_session.commit()
    if case == "ambiguous":
        from dataclasses import replace
        from importlib import import_module

        route = import_module("routes.integrations.get_context_preview")
        resolve = route.resolve_active_context_targets

        async def ambiguous_context(*args, **kwargs):
            resolved = await resolve(*args, **kwargs)
            assert len(resolved.entries) == 1
            return replace(resolved, entries=resolved.entries * 2)

        monkeypatch.setattr(route, "resolve_active_context_targets", ambiguous_context)
    client = AsyncMock()
    monkeypatch.setattr(preview_message, "graph_client_for_connection", client)
    response = await db_async_client.get(
        preview_url(conversation),
        params={
            "provider_key": "outlook_mail",
            "scope_id": "missing" if case == "no_match" else "mailbox",
            "ref": "message",
        },
        headers=headers,
    )
    assert response.status_code in {400, 404}, response.text
    client.assert_not_called()


@pytest.mark.parametrize(
    "provider,reference,status",
    [
        ("outlook_mail", "message!", 422),
        ("outlook_mail", "A" * 513, 422),
        ("gmail", "message=", 400),
        ("gmail", "A" * 129, 400),
    ],
)
async def test_conversation_preview_enforces_provider_reference_patterns(
    db_session, db_async_client, integration_identity, monkeypatch, provider, reference, status
):
    from integrations.gmail.operations import preview_message as gmail_preview
    from integrations.outlook_mail.operations import preview_message

    conversation = await preview_context(db_session, integration_identity, provider=provider)
    outlook_client, gmail_fetch = AsyncMock(), AsyncMock()
    monkeypatch.setattr(preview_message, "graph_client_for_connection", outlook_client)
    monkeypatch.setattr(gmail_preview, "preview_message", gmail_fetch)
    kind = "outlook_message" if provider == "outlook_mail" else "gmail_message"
    response = await db_async_client.get(
        preview_url(conversation, kind),
        params={"provider_key": provider, "scope_id": "mailbox", "ref": reference},
        headers=integration_identity["headers"],
    )
    assert response.status_code == status, response.text
    outlook_client.assert_not_called()
    gmail_fetch.assert_not_awaited()
