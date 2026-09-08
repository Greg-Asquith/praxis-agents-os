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
from integrations.outlook_mail.tools.utils import bounded_output
from services.agents.runtime.code_mode.stubs import render_tool_stub
from services.agents.runtime.tools.contract import validate_definition
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.context.results import IntegrationContextResult


def entry(mailbox_id="mailbox"):
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="outlook_mail",
        resource_type="outlook_mailbox",
        external_id=mailbox_id,
        display_name="dana@example.com",
        connection_id=uuid4(),
        connection_label="Outlook",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={"time_zone": "GMT Standard Time"},
    )


def context(*entries, tool_name):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=entries),
            db=object(),
            user=object(),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4(), name="Mail agent"),
            run=SimpleNamespace(id=uuid4(), user_id=uuid4()),
        ),
        tool_name=tool_name,
        tool_call_id="call-1",
    )


@pytest.mark.parametrize("definition", TOOL_DEFINITIONS, ids=lambda definition: definition.name)
def test_read_contracts_and_code_mode_stubs(definition):
    validate_definition(definition)
    assert definition.name in render_tool_stub(definition)
    assert definition.code_eligible and definition.default_policy == "auto"
    assert definition.integration_binding.requires_write is False


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


@pytest.mark.parametrize("mailboxes", [(), ("other",), ("mailbox", "mailbox")])
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


def test_complete_result_byte_bound():
    with pytest.raises(ModelRetry, match="too much data"):
        bounded_output(
            [
                IntegrationContextResult(
                    entry=entry(), status="success", data={"body": "界" * 300000}
                )
            ]
        )


@pytest.mark.parametrize("mailboxes", [(), ("other",), ("mailbox", "mailbox")])
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


async def test_resolver_resolves_exact_message_metadata(monkeypatch):
    from integrations.outlook_mail.entity_resolvers import message

    provider = SimpleNamespace(
        get=AsyncMock(
            return_value={
                "id": "message",
                "subject": "Invoice",
                "receivedDateTime": "2026-09-08T10:00:00Z",
            }
        )
    )
    monkeypatch.setattr(message, "mailbox_client_for_principal", AsyncMock(return_value=provider))
    ctx = SimpleNamespace(
        active_context=ResolvedActiveContext(entries=(entry(),)),
        db=object(),
        actor=object(),
        workspace=object(),
    )
    reference = OutlookMessageReference(mailbox_id="mailbox", message_id="message", label="Message")
    choices = await message.resolve_messages(ctx, [reference.model_dump()], {})
    assert len(choices) == 1 and choices[0].label == "Invoice"
    assert provider.get.call_args.kwargs["params"] == {
        "$select": "id,subject,from,receivedDateTime"
    }


@pytest.mark.parametrize("kind", ["itemAttachment", "referenceAttachment"])
async def test_unsupported_attachment_is_an_audited_error_entry(monkeypatch, kind):
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    client = SimpleNamespace(
        get=AsyncMock(return_value={"@odata.type": f"#microsoft.graph.{kind}"}),
        get_graph_bytes=AsyncMock(),
    )
    monkeypatch.setattr(
        "integrations.outlook_mail.tools.read_attachment.mailbox_client",
        AsyncMock(return_value=client),
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
    assert failure["error_code"] == "unsupported_attachment_kind"
    assert failure["error_message"] == "This attachment is not a file."
    client.get_graph_bytes.assert_not_awaited()
    assert audit.await_count == 1
    assert audit.call_args.kwargs["error_code"] == failure["error_code"]
    next(
        tool for tool in TOOL_DEFINITIONS if tool.name == "outlook_mail_read_attachment"
    ).output_model.model_validate(result)


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
        (
            {"userPrincipalName": "kai@example.com", "phones": [{"number": "800-555-0100"}]},
            "kai@example.com",
        ),
        ({"phones": [{"number": "800-555-0100"}]}, None),
        ({}, None),
        ({"userPrincipalName": "not-an-email"}, None),
        (
            {"emailAddresses": [{"address": "invalid"}], "userPrincipalName": "kai@example.com"},
            "kai@example.com",
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
    "mailboxes", [(), ("mailbox", "mailbox"), ("mailbox", "unique", "mailbox")]
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
    "changes,code",
    [
        ({"contentType": "image/png"}, "unsupported_attachment_type"),
        ({"size": -1}, "invalid_attachment_size"),
        ({"size": 101}, "attachment_too_large"),
        ({}, "attachment_conversion_failed"),
    ],
)
async def test_attachment_failure_reasons_survive_public_and_audit_outputs(
    monkeypatch, changes, code
):
    from integrations.outlook_mail.settings import outlook_mail_settings
    from utils.document_markdown import DocumentConversionError

    monkeypatch.setattr(outlook_mail_settings, "OUTLOOK_MAIL_ATTACHMENT_MAX_BYTES", 100)
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    provider = SimpleNamespace(
        get=AsyncMock(
            return_value={
                "@odata.type": "#microsoft.graph.fileAttachment",
                "contentType": "text/plain",
                "size": 4,
                **changes,
            }
        ),
        get_graph_bytes=AsyncMock(return_value=b"text"),
    )
    monkeypatch.setattr(
        "integrations.outlook_mail.tools.read_attachment.mailbox_client",
        AsyncMock(return_value=provider),
    )
    monkeypatch.setattr(
        "integrations.outlook_mail.operations.get_attachment.convert_document_to_markdown",
        AsyncMock(side_effect=DocumentConversionError("private provider body")),
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
    assert failure["error_code"] == audit.call_args.kwargs["error_code"] == code
    assert "private provider body" not in str(result) + str(audit.call_args)
    if code != "attachment_conversion_failed":
        provider.get_graph_bytes.assert_not_awaited()


@pytest.mark.parametrize("length", [None, "1", "5"])
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
        "integrations.outlook_mail.operations.get_attachment.convert_document_to_markdown",
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


@pytest.mark.parametrize("mailboxes", [(), ("other",), ("mailbox", "mailbox")])
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
        (("mailbox", "mailbox"), True),
        (("mailbox",), False),
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


@pytest.mark.parametrize("response", ["match", "mismatch", "missing"])
async def test_attachment_resolver_identity_and_bound(monkeypatch, response):
    from core.exceptions.integration import IntegrationNotFoundError
    from integrations.outlook_mail.entity_resolvers import attachment

    selected = entry()
    provider = SimpleNamespace(
        get=AsyncMock(
            side_effect=IntegrationNotFoundError("Missing") if response == "missing" else None,
            return_value={
                "id": "attachment/+=" if response == "match" else "other",
                "name": "Report",
            },
        )
    )
    client = AsyncMock(return_value=provider)
    monkeypatch.setattr(attachment, "mailbox_client_for_principal", client)
    ctx = SimpleNamespace(
        active_context=ResolvedActiveContext(entries=(selected,)),
        db=object(),
        actor=object(),
        workspace=object(),
    )
    reference = OutlookAttachmentReference(
        mailbox_id="mailbox",
        message_id="message/+=",
        attachment_id="attachment/+=",
        label="Attachment",
    )
    choices = await attachment.resolve_attachments(ctx, [reference.model_dump()] * 30, {})
    assert len(choices) == (25 if response == "match" else 0)
    assert provider.get.await_count == client.await_count == 25
    assert all(call.kwargs["entry"] is selected for call in client.call_args_list)
    assert provider.get.call_args.args == (
        "/me/messages/message%2F%2B%3D/attachments/attachment%2F%2B%3D",
    )
    assert provider.get.call_args.kwargs["params"] == {"$select": "id,name"}
    for choice in choices:
        assert choice.label == "Report"
        assert choice.identity == reference.identity()
        assert choice.scope_label == selected.display_name
        assert choice.value["mailbox_id"] == reference.mailbox_id
        assert choice.value["message_id"] == reference.message_id
        assert choice.value["attachment_id"] == reference.attachment_id
    provider.get.reset_mock()
    page = await attachment.search_attachments(ctx, "Report", {}, 20, None)
    assert page.choices == () and page.next_cursor is None
    provider.get.assert_not_awaited()


async def test_folder_tool_enriches_bounded_partial_results(monkeypatch):
    import httpx2

    from integrations.outlook_mail.operations.utils import WELL_KNOWN_FOLDERS
    from integrations.outlook_mail.tools.list_mail_folders import outlook_mail_list_folders
    from integrations.outlook_mail.tools.schemas import FoldersOutput
    from services.integrations.microsoft_graph import MicrosoftGraphClient, fixed_access_token

    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    lookups = []

    def handler(request):
        if request.url.path == "/v1.0/me/mailFolders":
            assert request.url.params["$top"] == "200"
            return httpx2.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "inbox-id",
                            "displayName": "Boîte de réception",
                            "unreadItemCount": 2,
                            "totalItemCount": 7,
                            "childFolderCount": 1,
                        },
                        *[{"id": f"custom-{i}", "displayName": "Rapports"} for i in range(250)],
                    ]
                },
            )
        name = request.url.path.rsplit("/", 1)[-1]
        lookups.append(name)
        if name == "archive":
            return httpx2.Response(404)
        return httpx2.Response(200, json={"id": f"{name}-id"})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport:
        provider = MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="outlook_mail", client=transport
        )

        async def client(_ctx, selected):
            if selected.external_id == "denied":
                raise IntegrationPermissionError(
                    "Mailbox access denied", provider_key="outlook_mail"
                )
            return provider

        monkeypatch.setattr(
            "integrations.outlook_mail.tools.list_mail_folders.mailbox_client", client
        )
        result = FoldersOutput.model_validate(
            await outlook_mail_list_folders(
                context(entry(), entry("denied"), tool_name="outlook_mail_list_folders")
            )
        )
    success, failure = result.results
    assert success.status == "success" and failure.status == "error"
    assert failure.error_code == "IntegrationPermissionError"
    assert lookups == sorted(WELL_KNOWN_FOLDERS)
    assert success.data.mailbox_time_zone == "GMT Standard Time"
    assert len(success.data.folders) == 200
    inbox, *custom = success.data.folders
    assert inbox.well_known_name == "inbox"
    assert inbox.name.content == "Boîte de réception"
    assert inbox.name.source_kind == "outlook_message" and inbox.name.source_ref == "inbox-id"
    assert (inbox.unread_count, inbox.total_count, inbox.child_folder_count) == (2, 7, 1)
    assert all(folder.well_known_name is None for folder in custom)
    assert all(folder.name.content == "Rapports" and folder.total_count == 0 for folder in custom)
    assert [call.kwargs["status"] for call in audit.call_args_list] == ["success", "failure"]
