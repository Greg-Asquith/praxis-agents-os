# apps/api/tests/integrations/gmail/test_gmail_provider.py

"""Gmail discovery and REST operation contracts."""

import base64
from email import message_from_bytes
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest

from core.exceptions.integration import (
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationValidationError,
)
from integrations.gmail.client import GmailClient
from integrations.gmail.discover_resources import GMAIL_SEND_SCOPE, discover_resources
from integrations.gmail.entity_resolvers.message import (
    search_gmail_messages,
)
from integrations.gmail.operations.preview_message import preview_message
from integrations.gmail.operations.send_message import html_to_text, send_message
from integrations.gmail.references import GmailMessageReference
from integrations.gmail.tools.read_message import gmail_read_message
from services.integrations import http as integration_http
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.discovery.run_discovery import _apply_granted_scope_permissions
from services.integrations.http import IntegrationRequestPolicy


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
            body_html="<p>Hello from <strong>Praxis</strong></p><script>alert(1)</script>",
        )

    padding = "=" * (-len(captured_raw) % 4)
    message = message_from_bytes(base64.urlsafe_b64decode(f"{captured_raw}{padding}"))
    assert message["To"] == "to@example.com"
    assert message["Cc"] == "cc@example.com"
    assert message["Bcc"] == "bcc@example.com"
    assert message["Subject"] == "Subject"
    assert message.is_multipart()
    parts = {
        part.get_content_type(): part.get_payload(decode=True)
        for part in message.walk()
        if not part.is_multipart()
    }
    assert b"Hello from Praxis" in parts["text/plain"]
    assert b"<strong>Praxis</strong>" in parts["text/html"]
    assert b"script" not in parts["text/html"]
    assert result == {"message_id": "sent-1"}


def test_html_to_text_flattens_blocks_lists_and_links() -> None:
    text = html_to_text(
        "<h1>Update</h1><p>Hi&nbsp;there,</p>"
        "<ul><li>First</li><li>Second</li></ul>"
        '<p><a href="https://example.com/report">View the report</a></p>'
        "<style>p{color:red}</style>"
    )
    assert "Update" in text
    assert "Hi there," in text
    assert "- First\n- Second" in text
    assert "View the report (https://example.com/report)" in text
    assert "color:red" not in text
    assert "\n\n\n" not in text


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
        result = await GmailClient(token, client=http_client).get(
            "users/me/profile",
            operation="x",
            policy=IntegrationRequestPolicy.READ,
        )

    assert result == {"ok": True}
    assert forces == [False, True]


@pytest.mark.parametrize(
    "failure",
    [
        "connect",
        "read_timeout",
    ],
)
async def test_gmail_send_failures_attempt_once(failure: str) -> None:
    attempts = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        if failure == "connect":
            raise httpx2.ConnectError("connect failed", request=request)
        if failure == "read_timeout":
            raise httpx2.ReadTimeout("response timed out", request=request)
        return httpx2.Response(int(failure), request=request)

    async def token(_force: bool) -> str:
        return "token"

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        with pytest.raises(IntegrationError):
            await GmailClient(token, client=http_client).post(
                "users/me/messages/send",
                operation="send_message",
                policy=IntegrationRequestPolicy.MUTATION,
                json={"raw": "message"},
            )

    assert attempts == 1


async def test_gmail_send_retries_exactly_once_after_auth_rejection() -> None:
    attempts = 0
    forces: list[bool] = []

    async def token(force: bool) -> str:
        forces.append(force)
        return "fresh" if force else "stale"

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        return httpx2.Response(401 if attempts == 1 else 200, json={}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        await GmailClient(token, client=http_client).post(
            "users/me/messages/send",
            operation="send_message",
            policy=IntegrationRequestPolicy.MUTATION,
            json={"raw": "message"},
        )

    assert attempts == 2
    assert forces == [False, True]


async def test_gmail_malformed_send_response_is_ambiguous() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"not-json", request=request)

    async def token(_force: bool) -> str:
        return "token"

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        with pytest.raises(IntegrationValidationError) as exc_info:
            await GmailClient(token, client=http_client).post(
                "users/me/messages/send",
                operation="send_message",
                policy=IntegrationRequestPolicy.MUTATION,
                json={"raw": "message"},
            )

    assert exc_info.value.failure_disposition is IntegrationFailureDisposition.AMBIGUOUS


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
        return httpx2.Response(404, json={"error": "boom"}, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        result = await preview_message(
            GmailClient(_static_token, client=http_client), message_id="m1"
        )

    assert result["content_type"] == "text"
    assert result["content"] == "plain only"
    assert result["meta"]["labels"] == []
    assert result["meta"]["thread_message_count"] is None


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
    assert [choice.value["message_id"] for choice in page.choices] == [
        f"m{index}" for index in range(20, 25)
    ]
    client_factory.assert_awaited_once()
    assert client_factory.await_args.kwargs["entry"] is active
    provider_search.assert_awaited_once_with(
        client_factory.return_value,
        query="is:unread",
        limit=25,
    )


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
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=entries)),
        tool_name="gmail_read_message",
    )
    client = object()
    provider_read = AsyncMock(return_value={"message_id": "m2", "subject": "Selected"})

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.gmail.tools.read_message.gmail_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr("integrations.gmail.tools.read_message.read_message", provider_read)
    monkeypatch.setattr(
        "integrations.gmail.tools.read_message.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await gmail_read_message(
        ctx,
        GmailMessageReference(
            mailbox_id=entries[1].external_id,
            message_id="m2",
            label="Selected",
            scope_label=entries[1].display_name,
        ),
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["external_id"] == entries[1].external_id
    assert "integration_resource_id" not in result["results"][0]
    provider_read.assert_awaited_once_with(client, message_id="m2")


async def _static_token(_force: bool) -> str:
    return "access-token"
