# apps/api/tests/integrations/gmail/test_gmail_provider.py

"""Gmail discovery and REST operation contracts."""

import asyncio
import base64
from email import message_from_bytes
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2

from core.exceptions.integration import IntegrationNotFoundError
from integrations.gmail.client import GmailClient
from integrations.gmail.discover_resources import GMAIL_SEND_SCOPE, discover_resources
from integrations.gmail.entity_resolvers.message import (
    _choice as gmail_message_choice,
    resolve_gmail_messages,
    search_gmail_messages,
)
from integrations.gmail.operations.preview_message import preview_message
from integrations.gmail.operations.read_message import MAX_BODY_CHARS, read_message
from integrations.gmail.operations.search_messages import search_messages
from integrations.gmail.operations.send_message import send_message
from integrations.gmail.references import GmailMessageReference
from integrations.gmail.tools.read_message import gmail_read_message
from services.integrations import http as integration_http
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.discovery.run_discovery import _apply_granted_scope_permissions


async def test_discovery_creates_one_mailbox_and_scope_gates_write(
    monkeypatch,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("/users/me/profile")
        return httpx2.Response(200, json={"emailAddress": "owner@example.com"}, request=request)

    original_client = httpx2.AsyncClient
    monkeypatch.setattr(
        integration_http.httpx2,
        "AsyncClient",
        lambda: original_client(transport=httpx2.MockTransport(handler)),
    )
    discovered = tuple(await discover_resources("access-token"))
    assert len(discovered) == 1
    assert discovered[0].external_id == "owner@example.com"
    assert discovered[0].required_write_scopes == (GMAIL_SEND_SCOPE,)

    writable = _apply_granted_scope_permissions(
        discovered,
        granted_scopes=frozenset({GMAIL_SEND_SCOPE}),
    )
    read_only = _apply_granted_scope_permissions(discovered, granted_scopes=frozenset())
    assert writable[0].writable is True
    assert read_only[0].writable is False


async def test_search_caps_results_and_fetches_metadata() -> None:
    seen_max_results: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/users/me/messages"):
            seen_max_results.append(request.url.params["maxResults"])
            return httpx2.Response(
                200,
                json={"messages": [{"id": "m1"}, {"id": "m2"}]},
                request=request,
            )
        message_id = request.url.path.rsplit("/", 1)[-1]
        return httpx2.Response(
            200,
            json={
                "id": message_id,
                "snippet": f"snippet-{message_id}",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "Subject", "value": f"Subject {message_id}"},
                    ]
                },
            },
            request=request,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = GmailClient(_static_token, client=http_client)
        result = await search_messages(client, query="is:unread", limit=100)

    assert seen_max_results == ["25"]
    assert result["total"] == 2
    assert result["messages"][0]["subject"].content == "Subject m1"


async def test_read_decodes_and_truncates_plain_text() -> None:
    body = "x" * (MAX_BODY_CHARS + 50)
    encoded = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "payload": {
                    "mimeType": "multipart/alternative",
                    "headers": [{"name": "Subject", "value": "Hostile subject"}],
                    "parts": [{"mimeType": "text/plain", "body": {"data": encoded}}],
                }
            },
            request=request,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        result = await read_message(GmailClient(_static_token, client=http_client), message_id="m1")

    assert result["truncated"] is True
    assert result["body"].content.startswith("x" * 100)
    assert "truncated" in result["body"].content.lower()


async def test_send_builds_rfc_message_and_returns_id() -> None:
    captured_raw = ""

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_raw
        captured_raw = request.read().decode()
        import json

        captured_raw = json.loads(captured_raw)["raw"]
        return httpx2.Response(200, json={"id": "sent-1"}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        result = await send_message(
            GmailClient(_static_token, client=http_client),
            to=["to@example.com"],
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
            subject="Subject",
            body_text="Hello from Praxis",
        )

    padding = "=" * (-len(captured_raw) % 4)
    message = message_from_bytes(base64.urlsafe_b64decode(f"{captured_raw}{padding}"))
    assert message["To"] == "to@example.com"
    assert message["Cc"] == "cc@example.com"
    assert message["Bcc"] == "bcc@example.com"
    assert message["Subject"] == "Subject"
    assert "Hello from Praxis" in message.get_payload()
    assert result == {"message_id": "sent-1"}


async def test_client_forces_one_refresh_after_unauthorized() -> None:
    calls = 0
    forces: list[bool] = []

    async def token(force: bool) -> str:
        forces.append(force)
        return "fresh" if force else "stale"

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        expected = "stale" if calls == 1 else "fresh"
        assert request.headers["Authorization"] == f"Bearer {expected}"
        return httpx2.Response(401 if calls == 1 else 200, json={"ok": True}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        result = await GmailClient(token, client=http_client).get("users/me/profile", operation="x")

    assert result == {"ok": True}
    assert forces == [False, True]


async def test_preview_extracts_html_labels_and_thread_meta() -> None:
    html = "<div><b>Rich body</b><img src='https://example.com/logo.png'></div>"
    encoded_html = base64.urlsafe_b64encode(html.encode()).decode().rstrip("=")
    encoded_plain = base64.urlsafe_b64encode(b"plain body").decode().rstrip("=")

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/users/me/messages/m1"):
            return httpx2.Response(
                200,
                json={
                    "threadId": "thread-1",
                    "labelIds": ["INBOX", "UNREAD", "CATEGORY_PERSONAL", "Label_7"],
                    "payload": {
                        "mimeType": "multipart/alternative",
                        "headers": [
                            {"name": "Subject", "value": "Quarterly update"},
                            {"name": "From", "value": "Ada <ada@example.com>"},
                            {"name": "To", "value": "team@example.com"},
                            {"name": "Date", "value": "Tue, 22 Jul 2026 09:00:00 +0000"},
                        ],
                        "parts": [
                            {"mimeType": "text/plain", "body": {"data": encoded_plain}},
                            {"mimeType": "text/html", "body": {"data": encoded_html}},
                        ],
                    },
                },
                request=request,
            )
        if request.url.path.endswith("/users/me/labels"):
            return httpx2.Response(
                200,
                json={
                    "labels": [
                        {"id": "Label_7", "name": "Clients", "type": "user"},
                        {"id": "INBOX", "name": "INBOX", "type": "system"},
                    ]
                },
                request=request,
            )
        assert request.url.path.endswith("/users/me/threads/thread-1")
        return httpx2.Response(
            200,
            json={"messages": [{"id": "m0"}, {"id": "m1"}, {"id": "m2"}]},
            request=request,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        result = await preview_message(
            GmailClient(_static_token, client=http_client), message_id="m1"
        )

    assert result["content_type"] == "html"
    assert result["content"] == html
    assert result["meta"]["subject"] == "Quarterly update"
    assert result["meta"]["labels"] == ["Inbox", "Clients"]
    assert result["meta"]["thread_message_count"] == 3


async def test_preview_falls_back_to_plain_text_and_survives_enrichment_failures() -> None:
    encoded_plain = base64.urlsafe_b64encode(b"plain only").decode().rstrip("=")

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/users/me/messages/m1"):
            return httpx2.Response(
                200,
                json={
                    "threadId": "thread-1",
                    "labelIds": ["Label_7"],
                    "payload": {
                        "mimeType": "text/plain",
                        "headers": [{"name": "Subject", "value": "Plain"}],
                        "body": {"data": encoded_plain},
                    },
                },
                request=request,
            )
        return httpx2.Response(500, json={"error": "boom"}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        result = await preview_message(
            GmailClient(_static_token, client=http_client), message_id="m1"
        )

    assert result["content_type"] == "text"
    assert result["content"] == "plain only"
    assert result["meta"]["labels"] == []
    assert result["meta"]["thread_message_count"] is None


def test_message_reference_truncates_long_subject() -> None:
    choice = gmail_message_choice(
        SimpleNamespace(integration_resource_id=uuid4(), display_name="Mailbox"),
        {"message_id": "m1", "subject": "x" * 501},
    )

    assert choice.label == "x" * 500
    assert choice.value["label"] == "x" * 500


async def test_message_hydration_omits_stale_item_without_aborting_batch(monkeypatch) -> None:
    entry = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="gmail",
        resource_type="gmail_mailbox",
        external_id="owner@example.com",
        display_name="owner@example.com",
        connection_id=uuid4(),
        connection_label="Gmail",
        connection_status="active",
        write_allowed=True,
    )
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(entry,)),
    )

    async def metadata(_client, message_id):
        if message_id == "deleted":
            raise IntegrationNotFoundError("Message not found", provider_key="gmail")
        return {"message_id": message_id, "subject": f"Subject {message_id}"}

    monkeypatch.setattr(
        "integrations.gmail.entity_resolvers.message.gmail_client_for_principal",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(
        "integrations.gmail.entity_resolvers.message.get_message_metadata",
        metadata,
    )

    choices = await resolve_gmail_messages(
        ctx,
        [
            GmailMessageReference(
                integration_resource_id=entry.integration_resource_id,
                external_id=message_id,
                label=message_id,
                scope_label=entry.display_name,
            )
            for message_id in ("first", "deleted", "last")
        ]
        + [
            GmailMessageReference(
                integration_resource_id=uuid4(),
                external_id="foreign-mailbox",
                label="Foreign mailbox",
            )
        ],
        {},
    )

    assert [choice.value["external_id"] for choice in choices] == ["first", "last"]


async def test_message_search_bounds_pagination_and_filters_active_scope(monkeypatch) -> None:
    active = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="gmail",
        resource_type="gmail_mailbox",
        external_id="active@example.com",
        display_name="active@example.com",
        connection_id=uuid4(),
        connection_label="Gmail",
        connection_status="active",
        write_allowed=True,
    )
    incompatible = ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="airtable",
        resource_type="airtable_base",
        external_id="app-other",
        display_name="Other base",
        connection_id=uuid4(),
        connection_label="Airtable",
        connection_status="active",
        write_allowed=True,
    )
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=(active, incompatible)),
    )
    client_factory = AsyncMock(return_value=object())
    provider_search = AsyncMock(
        return_value={
            "messages": [
                {"message_id": f"m{index}", "subject": f"Subject {index}"} for index in range(25)
            ]
        }
    )
    monkeypatch.setattr(
        "integrations.gmail.entity_resolvers.message.gmail_client_for_principal",
        client_factory,
    )
    monkeypatch.setattr(
        "integrations.gmail.entity_resolvers.message.search_messages",
        provider_search,
    )

    page = await search_gmail_messages(ctx, "is:unread", {}, 20, "20")

    assert len(page.choices) == 5
    assert page.next_cursor is None
    assert [choice.value["external_id"] for choice in page.choices] == [
        f"m{index}" for index in range(20, 25)
    ]
    client_factory.assert_awaited_once()
    assert client_factory.await_args.kwargs["entry"] is active
    provider_search.assert_awaited_once_with(
        client_factory.return_value,
        query="is:unread",
        limit=25,
    )


async def test_message_search_queries_active_mailboxes_concurrently(monkeypatch) -> None:
    entries = tuple(
        ResolvedContextEntry(
            integration_resource_id=uuid4(),
            provider_key="gmail",
            resource_type="gmail_mailbox",
            external_id=mailbox,
            display_name=mailbox,
            connection_id=uuid4(),
            connection_label="Gmail",
            connection_status="active",
            write_allowed=True,
        )
        for mailbox in ("first@example.com", "second@example.com")
    )
    ctx = SimpleNamespace(
        db=object(),
        actor=object(),
        workspace=object(),
        active_context=ResolvedActiveContext(entries=entries),
    )
    both_started = asyncio.Event()
    started = 0

    async def provider_search(client, **_kwargs):
        nonlocal started
        started += 1
        if started == len(entries):
            both_started.set()
        await both_started.wait()
        return {"messages": [{"message_id": client, "subject": client}]}

    monkeypatch.setattr(
        "integrations.gmail.entity_resolvers.message.gmail_client_for_principal",
        AsyncMock(side_effect=lambda *_args, **kwargs: kwargs["entry"].external_id),
    )
    monkeypatch.setattr(
        "integrations.gmail.entity_resolvers.message.search_messages",
        provider_search,
    )

    page = await asyncio.wait_for(
        search_gmail_messages(ctx, "is:unread", {}, 20, None),
        timeout=1,
    )

    assert [choice.label for choice in page.choices] == [entry.external_id for entry in entries]


async def test_read_message_targets_only_the_referenced_mailbox(monkeypatch) -> None:
    entries = tuple(
        ResolvedContextEntry(
            integration_resource_id=uuid4(),
            provider_key="gmail",
            resource_type="gmail_mailbox",
            external_id=mailbox,
            display_name=mailbox,
            connection_id=uuid4(),
            connection_label="Gmail",
            connection_status="active",
            write_allowed=True,
        )
        for mailbox in ("first@example.com", "second@example.com")
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=entries))
    )
    client = object()
    provider_read = AsyncMock(return_value={"message_id": "m2", "subject": "Selected"})

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return await kwargs["execute"]()

    monkeypatch.setattr(
        "integrations.gmail.tools.read_message.gmail_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr("integrations.gmail.tools.read_message.read_message", provider_read)
    monkeypatch.setattr(
        "integrations.gmail.tools.read_message.run_audited_operation",
        passthrough_audit,
    )

    result = await gmail_read_message(
        ctx,
        GmailMessageReference(
            integration_resource_id=entries[1].integration_resource_id,
            external_id="m2",
            label="Selected",
            scope_label=entries[1].display_name,
        ),
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["integration_resource_id"] == entries[1].integration_resource_id
    provider_read.assert_awaited_once_with(client, message_id="m2")


async def _static_token(_force: bool) -> str:
    return "access-token"
