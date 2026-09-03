"""Contract coverage for the shared Microsoft Graph engine seam."""

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx2
import pytest

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationNotFoundError,
    IntegrationPermissionError,
    IntegrationRateLimitError,
    IntegrationTimeoutError,
    IntegrationValidationError,
)
from core.settings import settings
from core.settings.integrations import IntegrationsSettingsMixin
from core.settings.microsoft_graph import MicrosoftGraphSettingsMixin
from models.integrations import IntegrationConnection
from services.integrations.http import IntegrationRequestPolicy, track_transport_attempts
from services.integrations.microsoft_graph import (
    MicrosoftGraphClient,
    authorization_url,
    classify_entra_token_error,
    entra_oauth_protocol,
    extract_token_identity,
    fetch_graph_identity,
    fixed_access_token,
    graph_client_for_connection,
    pacing,
    search_people,
    token_url,
    validate_entra_tenant,
)
from services.integrations.plugin import ExternalPrincipal

TENANT_ID = "b2c4d170-11e8-43a7-943e-a758a11b48d4"
USER_ID = "3a1c8019-6e25-4f52-8035-d2fa75a42cc1"


def test_microsoft_graph_settings_have_a_provider_specific_mixin() -> None:
    assert set(MicrosoftGraphSettingsMixin.__annotations__) == {
        "MICROSOFT_GRAPH_TENANT",
        "MICROSOFT_GRAPH_REQUESTS_PER_SECOND",
    }
    assert not set(MicrosoftGraphSettingsMixin.__annotations__) & set(
        IntegrationsSettingsMixin.__annotations__
    )


def _id_token(**overrides: object) -> str:
    claims = {
        "oid": USER_ID,
        "tid": TENANT_ID,
        "aud": "client-id",
        "iss": f"https://login.microsoftonline.com/{TENANT_ID}/v2.0",
        "exp": int(datetime.now(UTC).timestamp()) + 300,
        "preferred_username": "person@example.com",
        "name": "Example Person",
        **overrides,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"header.{encoded}.signature"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (TENANT_ID.upper(), TENANT_ID),
        ("Example.OnMicrosoft.com", "example.onmicrosoft.com"),
        ("organizations", "organizations"),
    ],
)
def test_validate_entra_tenant_accepts_supported_authorities(value: str, expected: str) -> None:
    assert validate_entra_tenant(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", " ", "common", "consumers", "tenant", "-example.com", "example..com", "https://x"],
)
def test_validate_entra_tenant_rejects_unsupported_authorities(value: str) -> None:
    with pytest.raises(ValueError, match="Microsoft Graph tenant"):
        validate_entra_tenant(value)


def test_entra_urls_and_protocol_are_tenant_specific() -> None:
    assert authorization_url(TENANT_ID) == (
        f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/authorize"
    )
    assert token_url(TENANT_ID) == (
        f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    )
    protocol = entra_oauth_protocol(client_id="client-id", expected_tenant_id=TENANT_ID)
    assert protocol.authorization_params == (
        ("response_mode", "query"),
        ("prompt", "select_account"),
    )
    assert protocol.scope_resource_prefix == "https://graph.microsoft.com/"
    assert protocol.revoke_token == "none"
    assert protocol.classify_token_error is classify_entra_token_error


def test_extract_token_identity_returns_bounded_verified_claims() -> None:
    principal = extract_token_identity(
        {"id_token": _id_token(name="x" * 300)},
        client_id="client-id",
        expected_tenant_id=TENANT_ID,
    )
    assert principal.external_id == USER_ID
    assert principal.label == "person@example.com"
    assert principal.connection_metadata == {
        "tenant_id": TENANT_ID,
        "user_principal_name": "person@example.com",
        "display_name": "x" * 255,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"id_token": "malformed"},
        {"id_token": _id_token(aud="wrong-client")},
        {"id_token": _id_token(iss="https://issuer.example.test")},
        {"id_token": _id_token(exp=0)},
        {"id_token": _id_token(tid=str(uuid4()))},
        {"id_token": _id_token(oid="not-a-uuid")},
    ],
)
def test_extract_token_identity_rejects_untrusted_claims(payload: dict[str, object]) -> None:
    with pytest.raises(IntegrationAuthError, match="identity response was rejected"):
        extract_token_identity(
            payload,
            client_id="client-id",
            expected_tenant_id=TENANT_ID,
        )


async def test_fetch_graph_identity_uses_the_me_endpoint() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200,
            headers={"Content-Type": "application/json", "request-id": "request-1"},
            json={
                "id": USER_ID,
                "mail": "mail@example.com",
                "userPrincipalName": "upn@example.com",
                "displayName": "Example Person",
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        principal = await fetch_graph_identity("access-token", client=http_client)

    request = requests[0]
    assert request.url.path == "/v1.0/me"
    assert request.url.params["$select"] == "id,mail,userPrincipalName,displayName"
    assert request.headers["authorization"] == "Bearer access-token"
    assert request.headers["accept"] == "application/json"
    assert request.headers["client-request-id"]
    assert request.headers["user-agent"].startswith("ISV|Praxis|PraxisAgents-microsoft_graph/")
    assert principal.external_id == USER_ID
    assert principal.label == "mail@example.com"
    assert principal.connection_metadata["user_principal_name"] == "upn@example.com"


async def test_missing_id_token_falls_back_to_graph_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.integrations.oauth import resolve_external_principal as exported_resolver

    fetched: list[str] = []
    resolver_module = __import__(
        "services.integrations.oauth.resolve_external_principal",
        fromlist=["resolve_provider_oauth_config"],
    )
    expected = ExternalPrincipal(USER_ID, "person@example.com")

    async def direct_fetch(access_token: str):
        fetched.append(access_token)
        return expected

    fallback_protocol = replace(
        entra_oauth_protocol(client_id="client-id", expected_tenant_id=TENANT_ID),
        fetch_identity=direct_fetch,
    )
    monkeypatch.setattr(
        resolver_module,
        "resolve_provider_oauth_config",
        lambda _key: type("Config", (), {"protocol": fallback_protocol})(),
    )
    result = await exported_resolver(
        provider_key="outlook_mail",
        access_token="access-token",  # noqa: S106
        token_payload={},
    )
    assert result is expected
    assert fetched == ["access-token"]


async def test_invalid_id_token_claims_do_not_fall_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.integrations.oauth import resolve_external_principal as exported_resolver

    fetched: list[str] = []

    async def direct_fetch(access_token: str) -> ExternalPrincipal:
        fetched.append(access_token)
        return ExternalPrincipal(USER_ID, "person@example.com")

    protocol = replace(
        entra_oauth_protocol(client_id="client-id", expected_tenant_id=TENANT_ID),
        fetch_identity=direct_fetch,
    )
    resolver_module = __import__(
        "services.integrations.oauth.resolve_external_principal",
        fromlist=["resolve_provider_oauth_config"],
    )
    monkeypatch.setattr(
        resolver_module,
        "resolve_provider_oauth_config",
        lambda _key: type("Config", (), {"protocol": protocol})(),
    )

    with pytest.raises(IntegrationAuthError):
        await exported_resolver(
            provider_key="outlook_mail",
            access_token="access-token",  # noqa: S106
            token_payload={"id_token": _id_token(aud="wrong-client")},
        )
    assert fetched == []


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (50076, "reauthorization_required"),
        (50079, "reauthorization_required"),
        (53003, "reauthorization_required"),
        (50173, "reauthorization_required"),
        (700082, "reauthorization_required"),
        (70008, "reauthorization_required"),
        (65001, "reauthorization_required"),
        (50105, "reauthorization_required"),
        (7000215, "client_credential_invalid"),
        (7000222, "client_credential_invalid"),
        (99999, None),
    ],
)
def test_classify_entra_token_error(code: int, expected: str | None) -> None:
    assert classify_entra_token_error({"error_codes": [code]}) == expected
    assert classify_entra_token_error({"error_description": f"AADSTS{code}: detail"}) == expected


async def test_graph_client_retries_auth_once_and_sends_outlook_headers() -> None:
    requests: list[httpx2.Request] = []
    tokens: list[bool] = []

    async def access_token(force: bool) -> str:
        tokens.append(force)
        return "fresh" if force else "stale"

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx2.Response(
                401,
                headers={"Content-Type": "application/json"},
                json={"error": {"code": "InvalidAuthenticationToken"}},
            )
        return httpx2.Response(
            200,
            headers={"Content-Type": "application/json", "request-id": "request-2"},
            json={"value": []},
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = MicrosoftGraphClient(
            access_token,
            provider_key="outlook_mail",
            client=http_client,
        )
        assert await client.get(
            "/me/messages",
            operation="list_messages",
            policy=IntegrationRequestPolicy.READ,
        ) == {"value": []}

    assert tokens == [False, True]
    assert requests[0].headers["authorization"] == "Bearer stale"
    assert requests[1].headers["authorization"] == "Bearer fresh"
    assert requests[1].headers["prefer"] == 'IdType="ImmutableId"'
    assert requests[1].headers["client-request-id"] != requests[0].headers["client-request-id"]
    assert requests[1].headers["user-agent"].startswith("ISV|Praxis|PraxisAgents-outlook_mail/")


@pytest.mark.parametrize(
    ("provider_key", "path"),
    [
        ("outlook_mail", "/me/messages/message-id/send"),
        ("outlook_calendar", "/me/events/event-id/accept"),
    ],
)
async def test_graph_client_accepts_empty_202_responses(
    provider_key: str,
    path: str,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(202, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = MicrosoftGraphClient(
            fixed_access_token("token"),
            provider_key=provider_key,
            client=http_client,
        )
        result = await client.post(
            path,
            operation="outlook_action",
            policy=IntegrationRequestPolicy.MUTATION,
        )

    assert result is None


async def test_graph_client_omits_immutable_header_for_drive_paths() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(request.headers)
        return httpx2.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={"id": "drive"},
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="sharepoint", client=http_client
        )
        await client.get(
            "/me/drive",
            operation="get_drive",
            policy=IntegrationRequestPolicy.READ,
        )
    assert "prefer" not in seen


@pytest.mark.parametrize(
    "path",
    [
        "/me/messages",
        "/me/mailFolders",
        "/me/events",
        "/me/calendars",
        "/me/calendarView",
        f"/users/{USER_ID}/messages",
        "/subscriptions",
    ],
)
async def test_graph_client_uses_immutable_ids_for_every_outlook_path(path: str) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(request.headers)
        return httpx2.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={"value": []},
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="outlook_calendar", client=http_client
        )
        await client.get(path, operation="outlook_read", policy=IntegrationRequestPolicy.READ)
    assert seen["prefer"] == 'IdType="ImmutableId"'


@pytest.mark.parametrize(
    ("status", "code", "error_type", "error_code"),
    [
        (404, "itemNotFound", IntegrationNotFoundError, None),
        (404, "ErrorItemNotFound", IntegrationNotFoundError, None),
        (404, "ResourceNotFound", IntegrationNotFoundError, None),
        (403, "accessDenied", IntegrationPermissionError, None),
        (403, "ErrorAccessDenied", IntegrationPermissionError, None),
        (403, "notAllowed", IntegrationPermissionError, None),
        (401, "InvalidAuthenticationToken", IntegrationAuthError, None),
        (429, "activityLimitReached", IntegrationRateLimitError, None),
        (400, "MailboxNotEnabledForRESTAPI", IntegrationValidationError, "mailbox_unavailable"),
        (400, "ErrorInvalidUser", IntegrationValidationError, "mailbox_unavailable"),
    ],
)
async def test_graph_client_maps_stable_error_codes(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    code: str,
    error_type: type[Exception],
    error_code: str | None,
) -> None:
    monkeypatch.setattr(settings, "INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS", 1)

    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status,
            headers={"Content-Type": "application/json", "request-id": "graph-request"},
            json={"error": {"code": code, "message": "provider-controlled detail"}},
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="outlook_mail", client=http_client
        )
        with pytest.raises(error_type) as exc_info:
            await client.get(
                "/me/messages",
                operation="list_messages",
                policy=IntegrationRequestPolicy.READ,
            )
    assert "provider-controlled detail" not in str(exc_info.value)
    assert getattr(exc_info.value, "error_code", None) == error_code


async def test_graph_client_honors_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.integrations import http

    waits: list[float] = []
    attempts = 0

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    def handler(_request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx2.Response(
                429,
                headers={"Content-Type": "application/json", "Retry-After": "2"},
                json={"error": {"code": "activityLimitReached"}},
            )
        return httpx2.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={"value": []},
        )

    monkeypatch.setattr(http.asyncio, "sleep", sleep)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="outlook_mail", client=http_client
        )
        await client.get(
            "/me/messages",
            operation="list_messages",
            policy=IntegrationRequestPolicy.READ,
        )
    assert waits == [2.0]


async def test_graph_pacing_runs_before_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.integrations.microsoft_graph import client as client_module

    events: list[str] = []

    @asynccontextmanager
    async def paced_request(_key: str) -> AsyncIterator[None]:
        events.append("pace")
        yield
        events.append("release")

    def handler(_request: httpx2.Request) -> httpx2.Response:
        events.append("dispatch")
        return httpx2.Response(
            200, headers={"Content-Type": "application/json"}, json={"value": []}
        )

    monkeypatch.setattr(client_module, "paced_request", paced_request)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = MicrosoftGraphClient(
            fixed_access_token("token"),
            provider_key="outlook_mail",
            client=http_client,
            pacing_key="connection",
        )
        await client.get(
            "/me/messages",
            operation="list_messages",
            policy=IntegrationRequestPolicy.READ,
        )
    assert events == ["pace", "dispatch", "release"]


async def test_graph_paces_each_retry_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.integrations import http
    from services.integrations.microsoft_graph import client as client_module

    events: list[str] = []
    request_ids: list[str] = []
    attempts = 0

    @asynccontextmanager
    async def paced_request(_key: str) -> AsyncIterator[None]:
        events.append("pace")
        yield
        events.append("release")

    async def sleep(_seconds: float) -> None:
        return None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        events.append("dispatch")
        request_ids.append(request.headers["client-request-id"])
        if attempts == 1:
            return httpx2.Response(503)
        return httpx2.Response(
            200, headers={"Content-Type": "application/json"}, json={"value": []}
        )

    monkeypatch.setattr(client_module, "paced_request", paced_request)
    monkeypatch.setattr(http.asyncio, "sleep", sleep)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = MicrosoftGraphClient(
            fixed_access_token("token"),
            provider_key="outlook_mail",
            client=http_client,
            pacing_key="connection",
        )
        await client.get(
            "/me/messages",
            operation="list_messages",
            policy=IntegrationRequestPolicy.READ,
        )
    assert events == ["pace", "dispatch", "release", "pace", "dispatch", "release"]
    assert len(set(request_ids)) == 2


async def test_graph_download_has_no_authorization_and_enforces_bound() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, content=b"five!")

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = MicrosoftGraphClient(
            fixed_access_token("secret"), provider_key="sharepoint", client=http_client
        )
        with pytest.raises(IntegrationValidationError, match="size limit"):
            await client.get_bytes(
                "https://93.184.216.34/content",
                operation="download_file",
                max_bytes=4,
            )
    assert "authorization" not in requests[0].headers


@pytest.mark.parametrize("retry_status", [429, 503])
async def test_graph_download_retries_transient_responses_and_counts_attempts(
    monkeypatch: pytest.MonkeyPatch,
    retry_status: int,
) -> None:
    from services.integrations import http

    attempts = 0

    async def sleep(_seconds: float) -> None:
        return None

    def handler(_request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx2.Response(retry_status, headers={"Retry-After": "0"})
        return httpx2.Response(200, content=b"file")

    monkeypatch.setattr(settings, "INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(http.asyncio, "sleep", sleep)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="sharepoint", client=http_client
        )
        with track_transport_attempts() as counter:
            result = await client.get_bytes(
                "https://93.184.216.34/content",
                operation="download_file",
                max_bytes=4,
            )
    assert result == b"file"
    assert (counter.requests, counter.attempts) == (1, 2)


async def test_graph_download_maps_timeout_without_retaining_signed_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_url = "https://93.184.216.34/content?signature=sensitive"

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("provider timed out", request=request)

    monkeypatch.setattr(settings, "INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS", 1)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="sharepoint", client=http_client
        )
        with (
            track_transport_attempts() as counter,
            pytest.raises(IntegrationTimeoutError) as exc_info,
        ):
            await client.get_bytes(secret_url, operation="download_file", max_bytes=4)
    assert (counter.requests, counter.attempts) == (1, 1)
    assert "sensitive" not in repr(exc_info.value.original_error)


async def test_graph_download_propagates_cancellation_and_counts_attempt() -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        raise asyncio.CancelledError

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="sharepoint", client=http_client
        )
        with track_transport_attempts() as counter, pytest.raises(asyncio.CancelledError):
            await client.get_bytes(
                "https://93.184.216.34/content",
                operation="download_file",
                max_bytes=4,
            )
    assert (counter.requests, counter.attempts) == (1, 1)


@pytest.mark.parametrize(
    "url",
    [
        "http://93.184.216.34/content",
        "https://127.0.0.1/content",
        "https://user:password@93.184.216.34/content",
    ],
)
async def test_graph_download_rejects_unsafe_destinations(url: str) -> None:
    client = MicrosoftGraphClient(fixed_access_token("token"), provider_key="sharepoint")
    with pytest.raises(IntegrationValidationError, match="public HTTPS destination"):
        await client.get_bytes(url, operation="download_file", max_bytes=4)


async def test_graph_download_rejects_hostname_resolving_to_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.integrations.microsoft_graph import client as client_module

    async def resolve(_host: str, _port: int) -> tuple[str, ...]:
        return ("10.0.0.1",)

    monkeypatch.setattr(client_module, "_resolve_host", resolve)
    client = MicrosoftGraphClient(fixed_access_token("token"), provider_key="sharepoint")
    with pytest.raises(IntegrationValidationError, match="public HTTPS destination"):
        await client.get_bytes(
            "https://download.example.test/content",
            operation="download_file",
            max_bytes=4,
        )


async def test_graph_download_failure_does_not_retain_signed_url() -> None:
    secret_url = "https://93.184.216.34/content?signature=sensitive"

    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(403)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="sharepoint", client=http_client
        )
        with pytest.raises(IntegrationPermissionError) as exc_info:
            await client.get_bytes(secret_url, operation="download_file", max_bytes=4)
    assert "sensitive" not in str(exc_info.value)
    assert "sensitive" not in repr(exc_info.value.original_error)


async def test_graph_client_normalizes_reserved_headers_case_insensitively() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, headers={"Content-Type": "application/json"}, json={})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = MicrosoftGraphClient(
            fixed_access_token("token"), provider_key="outlook_mail", client=http_client
        )
        await client.get(
            "/me/messages",
            operation="list_messages",
            policy=IntegrationRequestPolicy.READ,
            headers={
                "authorization": "Bearer attacker",
                "client-request-id": "attacker-id",
                "prefer": "respond-async",
            },
        )
    headers = requests[0].headers
    assert headers.get_list("authorization") == ["Bearer token"]
    assert headers.get_list("client-request-id") != ["attacker-id"]
    assert len(headers.get_list("client-request-id")) == 1
    assert headers.get_list("prefer") == ['respond-async, IdType="ImmutableId"']


async def test_graph_pagination_stops_at_item_and_page_bounds() -> None:
    requested_paths: list[str] = []

    async def get(path: str, **_kwargs: object) -> dict[str, object]:
        requested_paths.append(path)
        page = len(requested_paths)
        return {
            "value": [{"id": f"{page}-a"}, {"id": f"{page}-b"}],
            "@odata.nextLink": f"https://graph.microsoft.com/v1.0/items?page={page + 1}",
        }

    client = MicrosoftGraphClient(fixed_access_token("token"), provider_key="sharepoint")
    client.get = get  # type: ignore[method-assign]
    items = await client.paginate(
        "/items", operation="list_items", params={"$top": 2}, max_items=3, max_pages=5
    )
    assert [item["id"] for item in items] == ["1-a", "1-b", "2-a"]
    assert len(requested_paths) == 2

    requested_paths.clear()
    page_bounded = await client.paginate(
        "/items", operation="list_items", params=None, max_items=10, max_pages=1
    )
    assert [item["id"] for item in page_bounded] == ["1-a", "1-b"]
    assert len(requested_paths) == 1


async def test_search_people_bounds_request_and_parses_results() -> None:
    captured: dict[str, object] = {}

    class Client:
        async def post(self, path: str, **kwargs: object) -> dict[str, object]:
            captured.update(path=path, **kwargs)
            return {
                "value": [
                    {
                        "hitsContainers": [
                            {
                                "hits": [
                                    {
                                        "resource": {
                                            "displayName": "Ada Lovelace",
                                            "emailAddresses": [{"address": "ada@example.com"}],
                                            "jobTitle": "Engineer",
                                            "department": "Research",
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }

    results = await search_people(Client(), query=" Ada ", limit=100)  # type: ignore[arg-type]
    assert captured["path"] == "/search/query"
    body = captured["json"]
    assert isinstance(body, dict)
    assert body["requests"][0]["size"] == 25  # type: ignore[index]
    assert results == [("Ada Lovelace", "ada@example.com", "Engineer", "Research")]


def test_graph_client_for_connection_rejects_invalid_boundaries() -> None:
    class Db:
        def __init__(self, in_transaction: bool = False) -> None:
            self._in_transaction = in_transaction

        def in_transaction(self) -> bool:
            return self._in_transaction

    base = IntegrationConnection(
        id=uuid4(),
        provider_key="outlook_mail",
        label="Mailbox",
        owner_user_id=uuid4(),
        credential_id=uuid4(),
        connected_by_user_id=uuid4(),
        status="active",
        deleted=False,
    )
    with pytest.raises(IntegrationAuthError):
        graph_client_for_connection(Db(), base, expected_provider_key="sharepoint")  # type: ignore[arg-type]

    base.owner_workspace_id = uuid4()
    base.owner_user_id = None
    with pytest.raises(IntegrationAuthError):
        graph_client_for_connection(Db(), base, expected_provider_key="outlook_mail")  # type: ignore[arg-type]

    base.owner_user_id = uuid4()
    base.owner_workspace_id = None
    with pytest.raises(RuntimeError, match="close database transactions"):
        graph_client_for_connection(
            Db(in_transaction=True),  # type: ignore[arg-type]
            base,
            expected_provider_key="outlook_mail",
        )


async def test_graph_client_for_connection_dispatches_with_bound_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.integrations.microsoft_graph import connection_client as connection_module

    owner_user_id = uuid4()
    credential_id = uuid4()
    resolved_token = "resolved-token"
    connection = IntegrationConnection(
        id=uuid4(),
        provider_key="outlook_mail",
        label="Mailbox",
        owner_user_id=owner_user_id,
        credential_id=credential_id,
        connected_by_user_id=owner_user_id,
        status="active",
        deleted=False,
    )
    captured: dict[str, object] = {}

    class Db:
        def in_transaction(self) -> bool:
            return False

    async def ensure_fresh_credential(db: object, **kwargs: object) -> object:
        captured.update(db=db, **kwargs)
        return SimpleNamespace(
            provider_key="outlook_mail",
            owner_user_id=owner_user_id,
            owner_workspace_id=None,
            access_token=resolved_token,
        )

    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, headers={"Content-Type": "application/json"}, json={})

    db = Db()
    from services.integrations.credentials import (
        build_personal_oauth_access_token_resolver as resolver,
    )

    resolver_module = __import__(resolver.__module__, fromlist=["ensure_fresh_credential"])
    monkeypatch.setattr(resolver_module, "ensure_fresh_credential", ensure_fresh_credential)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = graph_client_for_connection(
            db,  # type: ignore[arg-type]
            connection,
            expected_provider_key="outlook_mail",
        )
        client._client = http_client
        await client.get(
            "/me/messages",
            operation="list_messages",
            policy=IntegrationRequestPolicy.READ,
        )
    assert captured == {
        "db": db,
        "credential_id": credential_id,
        "refresh_token": connection_module.refresh_oauth_credential,
        "force": False,
        "expected_provider_key": "outlook_mail",
        "expected_owner": (owner_user_id, None),
    }
    assert requests[0].headers["authorization"] == f"Bearer {resolved_token}"


async def test_pacing_uses_bounded_overflow_when_all_key_buckets_are_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pacing._reset_for_tests()
    monkeypatch.setattr(settings, "MICROSOFT_GRAPH_REQUESTS_PER_SECOND", 1_000_000.0)
    async with AsyncExitStack() as stack:
        for index in range(256):
            await stack.enter_async_context(pacing.paced_request(f"connection-{index}"))
        assert len(pacing._buckets) == 256
        async with pacing.paced_request("connection-overflow"):
            assert len(pacing._buckets) == 256
            assert "connection-overflow" not in pacing._buckets
    assert len(pacing._buckets) == 256


async def test_pacing_bucket_waits_after_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        nonlocal now
        waits.append(seconds)
        now += seconds

    pacing._reset_for_tests()
    monkeypatch.setattr(pacing, "monotonic", lambda: now)
    monkeypatch.setattr(pacing.asyncio, "sleep", sleep)
    for _ in range(5):
        async with pacing.paced_request("connection"):
            pass
    assert waits == [0.25]


async def test_pacing_holds_four_request_concurrency_per_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    maximum = 0
    four_started = asyncio.Event()
    release = asyncio.Event()

    async def handler(_request: httpx2.Request) -> httpx2.Response:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        if active == 4:
            four_started.set()
        await release.wait()
        active -= 1
        return httpx2.Response(200, headers={"Content-Type": "application/json"}, json={})

    pacing._reset_for_tests()
    monkeypatch.setattr(settings, "MICROSOFT_GRAPH_REQUESTS_PER_SECOND", 1_000_000.0)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        client = MicrosoftGraphClient(
            fixed_access_token("token"),
            provider_key="outlook_mail",
            client=http_client,
            pacing_key="connection",
        )
        tasks = [
            asyncio.create_task(
                client.get(
                    "/me/messages",
                    operation="list_messages",
                    policy=IntegrationRequestPolicy.READ,
                )
            )
            for _ in range(5)
        ]
        await asyncio.wait_for(four_started.wait(), timeout=1)
        await asyncio.sleep(0)
        assert maximum == 4
        release.set()
        await asyncio.gather(*tasks)
    assert maximum == 4
