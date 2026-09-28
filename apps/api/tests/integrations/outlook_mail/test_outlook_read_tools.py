# apps/api/tests/integrations/outlook_mail/test_outlook_read_tools.py

"""Outlook tool registration, context isolation, and audited result contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationPermissionError
from integrations.outlook_mail.references import OutlookAttachmentReference, OutlookMessageReference
from integrations.outlook_mail.tools import TOOL_DEFINITIONS
from integrations.outlook_mail.tools.read_attachment import outlook_mail_read_attachment
from integrations.outlook_mail.tools.read_message import outlook_mail_read_message
from integrations.outlook_mail.tools.search_messages import outlook_mail_search_messages
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.outlook_mail.support import context, entry


async def test_search_fan_out_records_partial_failure(monkeypatch):
    first, second = entry("first"), entry("second")
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )

    async def client(_ctx, selected):
        if selected.external_id == "second":
            raise IntegrationPermissionError("Mailbox access denied", provider_key="outlook_mail")
        return object()

    monkeypatch.setattr("integrations.outlook_mail.tools.search_messages.mailbox_client", client)
    monkeypatch.setattr(
        "integrations.outlook_mail.tools.search_messages.search_messages",
        AsyncMock(return_value=[]),
    )
    result = await outlook_mail_search_messages(
        context(first, second, tool_name="outlook_mail_search_messages")
    )
    assert [item["status"] for item in result["results"]] == ["success", "error"]
    assert result["results"][0]["data"]["mailbox_time_zone"] == "GMT Standard Time"
    assert audit.await_count == 2
    TOOL_DEFINITIONS[0].output_model.model_validate(result)
    assert "connection_id" not in str(result)
    assert "integration_resource_id" not in str(result)


@pytest.mark.parametrize(
    "mailboxes",
    [
        (),
    ],
)
async def test_message_targets_fail_closed_before_io(monkeypatch, mailboxes):
    client = AsyncMock()
    monkeypatch.setattr("integrations.outlook_mail.tools.read_message.mailbox_client", client)
    with pytest.raises(ModelRetry):
        await outlook_mail_read_message(
            context(
                *(entry(mailbox) for mailbox in mailboxes), tool_name="outlook_mail_read_message"
            ),
            OutlookMessageReference(mailbox_id="mailbox", message_id="message", label="Message"),
        )
    client.assert_not_awaited()


@pytest.mark.parametrize(
    "mailboxes",
    [
        (),
    ],
)
async def test_resolver_skips_unavailable_or_ambiguous_mailboxes(monkeypatch, mailboxes):
    from integrations.outlook_mail.entity_resolvers import message

    client = AsyncMock()
    monkeypatch.setattr(message, "mailbox_client_for_principal", client)
    ctx = SimpleNamespace(
        active_context=ResolvedActiveContext(entries=tuple(entry(value) for value in mailboxes))
    )
    reference = OutlookMessageReference(mailbox_id="mailbox", message_id="message", label="Message")
    assert await message.resolve_messages(ctx, [reference.model_dump()], {}) == ()
    client.assert_not_awaited()


@pytest.mark.parametrize(
    "person,address",
    [
        (
            {
                "emailAddresses": [{"address": "dana@example.com"}],
                "phones": [{"number": "800-555-0100"}],
            },
            "dana@example.com",
        ),
    ],
)
async def test_people_tool_returns_only_email_contacts(monkeypatch, person, address):
    from integrations.outlook_mail.tools.search_people import outlook_mail_search_people

    provider = SimpleNamespace(
        post=AsyncMock(
            return_value={"value": [{"hitsContainers": [{"hits": [{"resource": person}] * 30}]}]}
        )
    )
    monkeypatch.setattr(
        "integrations.outlook_mail.tools.search_people.mailbox_client",
        AsyncMock(return_value=provider),
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )
    result = await outlook_mail_search_people(
        context(entry(), tool_name="outlook_mail_search_people"), query="Dana", limit=25
    )
    [success] = result["results"]
    data = success["data"]
    assert data["count"] == len(data["people"]) == (25 if address else 0)
    for contact in data["people"]:
        assert contact["address"].content == address
        assert all(value.source_kind == "outlook_person" for value in contact.values())
    assert provider.post.call_args.kwargs["json"]["requests"][0]["size"] == 25


@pytest.mark.parametrize(
    "mailboxes",
    [
        (),
    ],
)
async def test_picker_search_excludes_ambiguous_mailboxes_before_io(monkeypatch, mailboxes):
    from integrations.outlook_mail.entity_resolvers import message

    provider = SimpleNamespace(
        paginate=AsyncMock(return_value=[{"id": str(i), "subject": "Report"} for i in range(25)])
    )
    client = AsyncMock(return_value=provider)
    monkeypatch.setattr(message, "mailbox_client_for_principal", client)
    ctx = SimpleNamespace(
        active_context=ResolvedActiveContext(entries=tuple(entry(value) for value in mailboxes)),
        db=object(),
        actor=object(),
        workspace=object(),
    )
    first = await message.search_messages(ctx, "", {}, 20, None)
    if "unique" not in mailboxes:
        assert first.choices == () and first.next_cursor is None
        client.assert_not_awaited()
        return
    second = await message.search_messages(ctx, "", {}, 20, first.next_cursor)
    assert len(first.choices) == 20 and first.next_cursor == "20"
    assert len(second.choices) == 5 and second.next_cursor is None
    assert message.OUTLOOK_MESSAGE_RESOLVER.max_page_size == 20
    assert all(call.kwargs["entry"].external_id == "unique" for call in client.call_args_list)
    assert all(call.kwargs["max_items"] == 25 for call in provider.paginate.call_args_list)


@pytest.mark.parametrize(
    "length",
    [
        None,
    ],
)
async def test_download_overflow_preserves_public_and_audit_reason(monkeypatch, length):
    import httpx2

    from integrations.outlook_mail.settings import outlook_mail_settings
    from services.integrations.microsoft_graph import MicrosoftGraphClient, fixed_access_token

    monkeypatch.setattr(outlook_mail_settings, "OUTLOOK_MAIL_ATTACHMENT_MAX_BYTES", 4)
    audit = AsyncMock(return_value=uuid4())
    conversion = AsyncMock()
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    monkeypatch.setattr(
        "integrations.outlook_mail.operations.get_attachment.convert_document_to_markdown_result",
        conversion,
    )
    requests = []

    class Stream(httpx2.AsyncByteStream):
        async def __aiter__(self):
            yield b"text"
            yield b"!"

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/$value"):
            return httpx2.Response(
                200, stream=Stream(), headers={} if length is None else {"Content-Length": length}
            )
        return httpx2.Response(
            200,
            json={
                "@odata.type": "#microsoft.graph.fileAttachment",
                "contentType": "text/plain",
                "size": 4,
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        provider = MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="outlook_mail", client=transport
        )
        monkeypatch.setattr(
            "integrations.outlook_mail.tools.read_attachment.mailbox_client",
            AsyncMock(return_value=provider),
        )
        result = await outlook_mail_read_attachment(
            context(entry(), tool_name="outlook_mail_read_attachment"),
            OutlookAttachmentReference(
                mailbox_id="mailbox",
                message_id="message",
                attachment_id="attachment",
                label="Attachment",
            ),
        )
    [failure] = result["results"]
    assert failure["status"] == "error"
    assert failure["error_code"] == audit.call_args.kwargs["error_code"] == "attachment_too_large"
    assert audit.await_count == 1
    assert len(requests) == 2
    conversion.assert_not_awaited()


@pytest.mark.parametrize(
    "mailboxes",
    [
        (),
    ],
)
async def test_attachment_targets_fail_closed_before_io(monkeypatch, mailboxes):
    client = AsyncMock()
    monkeypatch.setattr("integrations.outlook_mail.tools.read_attachment.mailbox_client", client)
    with pytest.raises(ModelRetry):
        await outlook_mail_read_attachment(
            context(
                *(entry(mailbox) for mailbox in mailboxes),
                tool_name="outlook_mail_read_attachment",
            ),
            OutlookAttachmentReference(
                mailbox_id="mailbox",
                message_id="message",
                attachment_id="attachment",
                label="Attachment",
            ),
        )
    client.assert_not_awaited()


async def test_message_attachment_reference_handoff(monkeypatch):
    import httpx2

    from integrations.outlook_mail.tools.schemas import AttachmentOutput, MessageOutput
    from services.integrations.microsoft_graph import MicrosoftGraphClient, fixed_access_token

    selected = entry()
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    paths = []
    message_path = b"/v1.0/me/messages/message%2Fid%2B%3D"
    attachment_path = message_path + b"/attachments/attachment%2Fid%2B%3D"
    metadata = {
        "id": "attachment/id+=",
        "name": "report.txt",
        "size": 4,
        "contentType": "text/plain",
        "@odata.type": "#microsoft.graph.fileAttachment",
    }

    def handler(request):
        path = request.url.raw_path.split(b"?")[0]
        paths.append(path)
        if path == message_path:
            return httpx2.Response(
                200,
                json={
                    "id": "message/id+=",
                    "subject": "Report",
                    "hasAttachments": True,
                    "body": {"contentType": "text", "content": "Read this report"},
                },
            )
        if path == message_path + b"/attachments":
            return httpx2.Response(200, json={"value": [metadata]})
        if path == attachment_path:
            return httpx2.Response(200, json=metadata)
        assert path == attachment_path + b"/$value"
        return httpx2.Response(200, content=b"text")

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        provider = MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="outlook_mail", client=transport
        )
        for module in ("read_message", "read_attachment"):
            monkeypatch.setattr(
                f"integrations.outlook_mail.tools.{module}.mailbox_client",
                AsyncMock(return_value=provider),
            )
        message = MessageOutput.model_validate(
            await outlook_mail_read_message(
                context(selected, tool_name="outlook_mail_read_message"),
                OutlookMessageReference(
                    mailbox_id="mailbox", message_id="message/id+=", label="Message"
                ),
            )
        )
        data = message.results[0].data
        assert data is not None
        [attachment] = data.attachments
        reference = attachment.reference
        assert (reference.mailbox_id, reference.message_id, reference.attachment_id) == (
            "mailbox",
            "message/id+=",
            "attachment/id+=",
        )
        output = AttachmentOutput.model_validate(
            await outlook_mail_read_attachment(
                context(selected, tool_name="outlook_mail_read_attachment"), reference
            )
        )
    assert paths == [
        message_path,
        message_path + b"/attachments",
        attachment_path,
        attachment_path + b"/$value",
    ]
    result = output.results[0]
    assert result.status == "success"
    assert result.data.markdown.content == "text"
    assert result.data.size_bytes == 4
    assert result.data.source == "text" and result.data.truncated is False
    assert result.data.mailbox_time_zone == data.mailbox_time_zone == "GMT Standard Time"
    for node in (data.subject, data.body, attachment.name, result.data.markdown):
        assert node.source_kind == "outlook_message" and node.source_ref == "message/id"
    assert [call.kwargs["external_ref"] for call in audit.call_args_list] == [
        "message/id+=",
        "attachment/id+=",
    ]
    assert all(call.kwargs["status"] == "success" for call in audit.call_args_list)
    public = message.model_dump_json() + output.model_dump_json()
    assert str(selected.connection_id) not in public
    assert str(selected.integration_resource_id) not in public


@pytest.mark.parametrize(
    "mailboxes,valid",
    [
        ((), True),
        (("other",), True),
    ],
)
async def test_attachment_resolver_denies_before_credentials(monkeypatch, mailboxes, valid):
    from integrations.outlook_mail.entity_resolvers import attachment

    client = AsyncMock()
    monkeypatch.setattr(attachment, "mailbox_client_for_principal", client)
    ctx = SimpleNamespace(
        active_context=ResolvedActiveContext(entries=tuple(entry(value) for value in mailboxes))
    )
    value = (
        OutlookAttachmentReference(
            mailbox_id="mailbox",
            message_id="message",
            attachment_id="attachment",
            label="Attachment",
        ).model_dump()
        if valid
        else {"mailbox_id": "mailbox"}
    )
    assert await attachment.resolve_attachments(ctx, [value], {}) == ()
    client.assert_not_awaited()
