# apps/api/tests/integrations/gmail/test_gmail_provider.py

"""Gmail discovery and REST operation contracts."""

import base64
from email import message_from_bytes

import httpx2

from integrations.gmail.client import GmailClient
from integrations.gmail.discover_resources import GMAIL_SEND_SCOPE, discover_resources
from integrations.gmail.operations.read_message import MAX_BODY_CHARS, read_message
from integrations.gmail.operations.search_messages import search_messages
from integrations.gmail.operations.send_message import send_message
from services.integrations import http as integration_http
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


async def _static_token(_force: bool) -> str:
    return "access-token"
