# apps/api/tests/integrations/outlook_mail/test_save_attachment.py

"""Original-byte attachment saves, pre-download rejections, and scoped audit evidence."""

import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from pydantic_ai import ModelRetry

from integrations.outlook_mail.references import OutlookAttachmentReference
from integrations.outlook_mail.settings import outlook_mail_settings
from integrations.outlook_mail.tools.save_attachment import outlook_mail_save_attachment
from integrations.outlook_mail.tools.schemas import SavedAttachmentOutput
from services.agents.runtime.untrusted import frame_untrusted_content
from services.integrations.microsoft_graph import MicrosoftGraphClient, fixed_access_token
from tests.integrations.outlook_mail.support import context, entry
from tests.support.documents import tiny_pdf

PDF = tiny_pdf("Signed contract")
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6a1sAAAAASUVORK5CYII="
)
EFFECTS = (
    "reserve_file_revision",
    "create_file_with_revision",
    "resolve_folder_by_name",
    "create_conversation_file_references",
)


@asynccontextmanager
async def transaction():
    yield


def reference(mailbox_id="mailbox"):
    return OutlookAttachmentReference(
        mailbox_id=mailbox_id, message_id="message", attachment_id="attachment", label="Attachment"
    )


def save_context():
    ctx = context(entry(), tool_name="outlook_mail_save_attachment")
    ctx.deps.db = SimpleNamespace(begin_nested=transaction)
    ctx.deps.user = SimpleNamespace(id=uuid4())
    ctx.deps.conversation = SimpleNamespace(id=uuid4())
    return ctx


def patch_effects(monkeypatch, **overrides):
    effects = {name: overrides.get(name, AsyncMock()) for name in EFFECTS}
    for name, effect in effects.items():
        monkeypatch.setattr(f"services.integrations.files.create_copy.{name}", effect)
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    return effects, audit


async def save(monkeypatch, ctx, handler, folder=None):
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        provider = MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="outlook_mail", client=transport
        )
        monkeypatch.setattr(
            "integrations.outlook_mail.tools.save_attachment.mailbox_client",
            AsyncMock(return_value=provider),
        )
        return await outlook_mail_save_attachment(ctx, reference(), folder)


def graph_handler(requests, metadata, content=b"", headers=None):
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/$value"):
            return httpx2.Response(200, content=content, headers=headers)
        return httpx2.Response(
            200, json={"@odata.type": "#microsoft.graph.fileAttachment", **metadata}
        )

    return handler


@pytest.mark.parametrize(
    "name,content_type,content",
    [("contract.pdf", "application/pdf", PDF), ("photo.png", "image/png", PNG)],
)
async def test_save_retains_original_bytes_and_records_file_identity(
    monkeypatch, name, content_type, content
):
    ctx = save_context()
    saved_file = SimpleNamespace(id=uuid4(), name=name)
    saved_revision = SimpleNamespace(id=uuid4())
    folder = SimpleNamespace(id=uuid4())
    effects, audit = patch_effects(
        monkeypatch,
        create_file_with_revision=AsyncMock(
            return_value=SimpleNamespace(
                file=saved_file, revision=saved_revision, bytes_written=len(content)
            )
        ),
        resolve_folder_by_name=AsyncMock(return_value=folder),
    )
    requests = []
    metadata = {"name": name, "contentType": content_type, "size": len(content) + 200}
    result = await save(
        monkeypatch, ctx, graph_handler(requests, metadata, content), folder="  Contracts "
    )

    data = SavedAttachmentOutput.model_validate(result).results[0].data
    assert data is not None
    assert data.file_id == data.reference.entity_id == saved_file.id
    assert data.revision_id == saved_revision.id
    assert data.content_type == content_type and data.size_bytes == len(content)
    assert data.attachment.attachment_id == "attachment"
    create = effects["create_file_with_revision"].await_args.kwargs
    assert create["content"] == content and create["content_type"] == content_type
    assert create["actor"].agent_id == ctx.deps.agent.id
    assert create["resolved_folder"] is folder
    assert effects["resolve_folder_by_name"].await_args.kwargs["name"] == "Contracts"
    effects["create_conversation_file_references"].assert_awaited_once_with(
        ctx.deps.db,
        workspace_id=ctx.deps.workspace.id,
        conversation_id=ctx.deps.conversation.id,
        file_ids=[saved_file.id],
        created_by_user_id=ctx.deps.user.id,
    )
    assert len(requests) == 2
    evidence = audit.await_args.kwargs
    assert evidence["status"] == "success" and evidence["external_ref"] == "attachment"
    detail = evidence["operation_detail"]
    assert detail.target.attributes == {"mailbox_id": "mailbox", "message_id": "message"}
    assert detail.outcome_groups[0].outcomes[0].effects[0].fields == {
        "file_id": str(saved_file.id),
        "revision_id": str(saved_revision.id),
    }
    assert (
        "PRAXIS_UNTRUSTED_CONTENT" in frame_untrusted_content(result)["results"][0]["data"]["name"]
    )
    visible = str(result) + str(detail)
    assert content.hex() not in str(evidence)
    assert str(ctx.deps.active_context.entries[0].connection_id) not in visible


@pytest.mark.parametrize(
    "metadata,code",
    [
        (
            {"name": "setup.bin", "contentType": "application/octet-stream"},
            "unsupported_attachment_type",
        ),
        ({"name": "invoice.exe", "contentType": "application/pdf"}, "attachment_type_mismatch"),
    ],
)
async def test_rejected_types_stop_before_download(monkeypatch, metadata, code):
    effects, _audit = patch_effects(monkeypatch)
    requests = []
    result = await save(
        monkeypatch, save_context(), graph_handler(requests, {**metadata, "size": 4})
    )
    assert result["results"][0]["error_code"] == code
    assert len(requests) == 1
    for effect in effects.values():
        effect.assert_not_awaited()


async def test_streamed_overflow_with_understated_length_creates_no_file(monkeypatch):
    monkeypatch.setattr(outlook_mail_settings, "OUTLOOK_MAIL_ATTACHMENT_MAX_BYTES", 4)
    effects, _audit = patch_effects(monkeypatch)
    metadata = {"name": "notes.txt", "contentType": "text/plain", "size": 4}
    result = await save(
        monkeypatch,
        save_context(),
        graph_handler([], metadata, b"text!", headers={"Content-Length": "4"}),
    )
    assert result["results"][0]["error_code"] == "attachment_too_large"
    for effect in effects.values():
        effect.assert_not_awaited()


async def test_storage_failure_publishes_no_file(monkeypatch):
    effects, audit = patch_effects(
        monkeypatch, create_file_with_revision=AsyncMock(side_effect=OSError("storage down"))
    )
    metadata = {"name": "notes.txt", "contentType": "text/plain", "size": 4}
    result = await save(monkeypatch, save_context(), graph_handler([], metadata, b"text"))
    [failure] = result["results"]
    assert failure["status"] == "error" and failure["data"] is None
    effects["create_conversation_file_references"].assert_not_awaited()
    assert not any(call.kwargs["status"] == "success" for call in audit.await_args_list)


@pytest.mark.parametrize("mailboxes", [(), ("other",)])
async def test_unselected_mailbox_stops_before_credentials(monkeypatch, mailboxes):
    client = AsyncMock()
    monkeypatch.setattr("integrations.outlook_mail.tools.save_attachment.mailbox_client", client)
    ctx = context(
        *(entry(mailbox) for mailbox in mailboxes), tool_name="outlook_mail_save_attachment"
    )
    with pytest.raises(ModelRetry):
        await outlook_mail_save_attachment(ctx, reference())
    client.assert_not_awaited()
