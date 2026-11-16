# apps/api/tests/routes/integrations/test_context_file_sources.py

"""Person-initiated views and saves of Outlook attachments from a conversation card."""

from unittest.mock import AsyncMock

import httpx2
import pytest
from sqlalchemy import select

from core.database import set_session_tenant_context
from integrations.outlook_mail import PROVIDER
from models.audit_event import AuditEvent
from models.files import File, FileReference, FileRevision
from models.workspace import WorkspaceRole
from services.integrations.manifest import PROVIDER_MANIFESTS
from services.integrations.microsoft_graph import MicrosoftGraphClient, fixed_access_token
from services.integrations.plugin import PROVIDER_PLUGINS
from tests.routes.integrations.conftest import create_identity
from tests.routes.integrations.test_conversation_preview_routes import preview_context
from tests.support.documents import tiny_pdf

PDF = tiny_pdf("Signed contract")


@pytest.fixture(autouse=True)
def outlook_provider(integration_route_settings, local_storage):
    PROVIDER_PLUGINS["outlook_mail"] = PROVIDER
    PROVIDER_MANIFESTS["outlook_mail"] = PROVIDER.manifest


def save_url(conversation, action="file-saves"):
    return f"/api/v1/integrations/conversations/{conversation.id}/{action}"


def save_body(mailbox_id="mailbox"):
    return {
        "provider_key": "outlook_mail",
        "reference": {
            "entity_kind": "outlook_attachment",
            "label": "Outlook attachment",
            "mailbox_id": mailbox_id,
            "message_id": "message",
            "attachment_id": "attachment",
        },
    }


def graph_handler(request, name="contract.pdf", content_type="application/pdf"):
    if request.url.path.endswith("/$value"):
        return httpx2.Response(200, content=PDF)
    return httpx2.Response(
        200,
        json={
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": name,
            "contentType": content_type,
            "size": len(PDF),
        },
    )


async def post_with_graph(db_async_client, monkeypatch, url, headers, handler=graph_handler):
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        client = MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="outlook_mail", client=transport
        )
        monkeypatch.setattr(
            "integrations.outlook_mail.file_sources.mailbox_client_for_principal",
            AsyncMock(return_value=client),
        )
        return await db_async_client.post(url, json=save_body(), headers=headers)


async def test_selected_mailbox_saves_file_as_person_with_link_and_audit(
    db_session, db_async_client, integration_identity, monkeypatch
):
    user, workspace = integration_identity["user"], integration_identity["workspace"]
    conversation = await preview_context(db_session, integration_identity)
    response = await post_with_graph(
        db_async_client, monkeypatch, save_url(conversation), integration_identity["headers"]
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "contract.pdf" and body["content_type"] == "application/pdf"
    assert body["size_bytes"] == len(PDF)
    await set_session_tenant_context(db_session, workspace_id=workspace.id, user_id=user.id)
    file = await db_session.get(File, body["file_id"])
    revision = await db_session.get(FileRevision, file.current_revision_id)
    assert revision.created_by_user_id == user.id and revision.created_by_agent_id is None
    link = await db_session.scalar(select(FileReference).where(FileReference.file_id == file.id))
    assert link.target_type == "conversation" and link.target_id == conversation.id
    audit = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.resource_id == str(file.id))
    )
    assert audit.actor_type == "user" and audit.actor_id == str(user.id)
    assert audit.details["source"]["attachment_id"] == "attachment"
    assert audit.details["revision_id"] == str(revision.id)
    assert PDF.hex() not in str(audit.details)


async def test_view_returns_sandboxed_bytes_without_saving(
    db_session, db_async_client, integration_identity, monkeypatch
):
    conversation = await preview_context(db_session, integration_identity)
    response = await post_with_graph(
        db_async_client,
        monkeypatch,
        save_url(conversation, "file-views"),
        integration_identity["headers"],
    )
    assert response.status_code == 200, response.text
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-security-policy"].startswith("sandbox")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert await db_session.scalar(select(File.id)) is None


async def test_view_refuses_types_a_browser_cannot_show_safely(
    db_session, db_async_client, integration_identity, monkeypatch
):
    conversation = await preview_context(db_session, integration_identity)
    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    response = await post_with_graph(
        db_async_client,
        monkeypatch,
        save_url(conversation, "file-views"),
        integration_identity["headers"],
        handler=lambda request: graph_handler(request, "notes.docx", docx),
    )
    assert response.status_code == 400, response.text
    assert "Save it to Files" in response.text


@pytest.mark.parametrize("case", ["unselected_mailbox", "other_member"])
async def test_save_denies_unavailable_targets_before_credentials(
    db_session, db_async_client, integration_identity, monkeypatch, case
):
    headers = integration_identity["headers"]
    if case == "other_member":
        _user, _workspace, _membership, headers = await create_identity(
            db_session, role=WorkspaceRole.OWNER, workspace=integration_identity["workspace"]
        )
    conversation = await preview_context(db_session, integration_identity)
    client = AsyncMock()
    monkeypatch.setattr(
        "integrations.outlook_mail.file_sources.mailbox_client_for_principal", client
    )
    response = await db_async_client.post(
        save_url(conversation),
        json=save_body("other" if case == "unselected_mailbox" else "mailbox"),
        headers=headers,
    )
    assert response.status_code in {400, 404}, response.text
    client.assert_not_awaited()
    assert await db_session.scalar(select(File.id)) is None
