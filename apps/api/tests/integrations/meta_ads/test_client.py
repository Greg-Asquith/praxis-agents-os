"""Checks Meta transport boundaries, retry policy, and safe errors."""

import hashlib
import hmac
import logging
from unittest.mock import AsyncMock

import httpx2
import pytest
from pydantic import SecretStr

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationConnectionError,
    IntegrationPermissionError,
    IntegrationRateLimitError,
    IntegrationValidationError,
)
from core.settings import settings
from integrations.meta_ads.client import (
    META_GRAPH_API_VERSION,
    MetaAdsClient,
    ad_account_path,
    normalize_ad_account_id,
)
from services.integrations.http import IntegrationRequestPolicy
from tests.integrations.meta_ads.support import TOKEN, DiscoveryTransport, static_token

READ = IntegrationRequestPolicy.READ


@pytest.mark.parametrize("configured", [False, True])
async def test_bearer_and_optional_proof_stay_out_of_logs(configured, caplog) -> None:
    requests = []
    secret = SecretStr("test-meta-app-secret") if configured else None
    proof = hmac.new(b"test-meta-app-secret", TOKEN.encode(), hashlib.sha256).hexdigest()

    def handler(request):
        requests.append(request)
        return httpx2.Response(
            200,
            json={"id": "700"},
            headers={"X-Business-Use-Case-Usage": '{"900":[{"call_count":5}]}'},
            request=request,
        )

    caplog.set_level(logging.DEBUG)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        client = MetaAdsClient(static_token, app_secret=secret, client=http)
        assert await client.graph_get("me", operation="identity", policy=READ) == {"id": "700"}

    assert requests[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert requests[0].url.path == f"/{META_GRAPH_API_VERSION}/me"
    assert TOKEN not in str(requests[0].url)
    assert requests[0].url.params.get("appsecret_proof") == (proof if configured else None)
    assert TOKEN not in caplog.text
    assert proof not in caplog.text


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (190, IntegrationAuthError),
        (10, IntegrationPermissionError),
        (200, IntegrationPermissionError),
        (299, IntegrationPermissionError),
        (100, IntegrationValidationError),
        (999, IntegrationValidationError),
    ],
)
async def test_error_codes_have_bounded_safe_details(code, expected) -> None:
    def handler(request):
        return httpx2.Response(
            400,
            json={"error": {"code": code, "message": TOKEN * 100, "fbtrace_id": "trace-123"}},
            request=request,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        with pytest.raises(expected) as failure:
            await MetaAdsClient(static_token, client=http).graph_get(
                "me", operation="identity", policy=READ
            )
    assert "trace-123" in str(failure.value)
    assert TOKEN not in str(failure.value)
    assert len(failure.value.user_message) <= 500


@pytest.mark.parametrize(
    ("message", "configured", "guidance"),
    [
        ("Invalid appsecret_proof provided in the API argument", True, "different Meta app"),
        (
            "API calls from the server require an appsecret_proof argument",
            False,
            "administrator to add the app secret",
        ),
    ],
)
async def test_app_secret_mismatches_explain_operator_action(message, configured, guidance) -> None:
    def handler(request):
        return httpx2.Response(
            400, json={"error": {"code": 100, "message": message}}, request=request
        )

    secret = SecretStr("test-app-secret") if configured else None
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        with pytest.raises(IntegrationValidationError, match=guidance):
            await MetaAdsClient(static_token, app_secret=secret, client=http).graph_get(
                "me", operation="identity", policy=READ
            )


@pytest.mark.parametrize("code", [4, 17, 32, 613, *range(80000, 80015), 1, 2])
async def test_retryable_graph_codes_use_shared_bounded_retries(code, monkeypatch) -> None:
    attempts = []
    sleep = AsyncMock()
    monkeypatch.setattr("services.integrations.http.asyncio.sleep", sleep)
    monkeypatch.setattr(settings, "INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS", 2)

    def handler(request):
        attempts.append(request)
        return httpx2.Response(
            400,
            json={"error": {"code": code}},
            headers={"Retry-After": "1"},
            request=request,
        )

    expected = IntegrationConnectionError if code in (1, 2) else IntegrationRateLimitError
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        with pytest.raises(expected):
            await MetaAdsClient(static_token, client=http).graph_get(
                "me", operation="identity", policy=READ
            )
    assert len(attempts) == 2
    sleep.assert_awaited_once_with(1.0)


async def test_transient_flag_can_recover(monkeypatch) -> None:
    attempts = []
    monkeypatch.setattr("services.integrations.http.asyncio.sleep", AsyncMock())

    def handler(request):
        attempts.append(request)
        return httpx2.Response(
            400 if len(attempts) == 1 else 200,
            json={"error": {"code": 999, "is_transient": True}}
            if len(attempts) == 1
            else {"id": "700"},
            request=request,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        assert await MetaAdsClient(static_token, client=http).graph_get(
            "me", operation="identity", policy=READ
        ) == {"id": "700"}
    assert len(attempts) == 2


@pytest.mark.parametrize("cap", [1, 2])
async def test_paging_follows_next_and_reports_cap(cap) -> None:
    transport = DiscoveryTransport()
    async with httpx2.AsyncClient(transport=transport) as http:
        rows, truncated = await MetaAdsClient(static_token, client=http).graph_get_paged(
            "me/adaccounts", params={"limit": 100}, operation="accounts", policy=READ, max_pages=cap
        )
    assert len(rows) == cap
    assert truncated is (cap == 1)
    assert all(request.url.params["limit"] == "100" for request in transport.requests)


@pytest.mark.parametrize(
    "next_url",
    [
        "https://example.com/me?after=2",
        "http://graph.facebook.com/me?after=2",
        "https://graph.facebook.com/v26.0/other?after=2",
        "https://user@graph.facebook.com/v26.0/me/adaccounts?after=2",
        "https://graph.facebook.com:444/v26.0/me/adaccounts?after=2",
        "https://graph.facebook.com/v26.0/me/adaccounts?after=2&after=3",
        "https://graph.facebook.com/v25.0/700/adaccounts?after=2",
        "https://graph.facebook.com/v26.0/700/campaigns?after=2",
    ],
)
async def test_paging_rejects_untrusted_next_urls(next_url) -> None:
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(
            200, json={"data": [], "paging": {"next": next_url}}, request=request
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        with pytest.raises(IntegrationValidationError):
            await MetaAdsClient(static_token, client=http).graph_get_paged(
                "me/adaccounts", operation="accounts", policy=READ
            )
    assert len(requests) == 1


async def test_paging_never_forwards_tokens_or_proofs_from_next() -> None:
    requests = []

    def handler(request):
        requests.append(request)
        payload = {"data": []}
        if len(requests) == 1:
            payload["paging"] = {
                "next": "https://graph.facebook.com/v26.0/me/adaccounts?after=2&access_token=foreign&appsecret_proof=foreign-proof"
            }
        return httpx2.Response(200, json=payload, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        await MetaAdsClient(static_token, client=http).graph_get_paged(
            "me/adaccounts", operation="accounts", policy=READ
        )
    assert len(requests) == 2
    assert requests[1].url.params["after"] == "2"
    assert "access_token" not in requests[1].url.params
    assert "appsecret_proof" not in requests[1].url.params


@pytest.mark.parametrize("value", ["123", "act_123"])
def test_account_ids_normalise_to_one_identity(value) -> None:
    assert normalize_ad_account_id(value) == "123"
    assert ad_account_path(normalize_ad_account_id(value)) == "act_123"


@pytest.mark.parametrize(
    "value", ["", "act_", "12/3", "123?token=x", "-123", "\uff11\uff12\uff13", "12 3"]
)
def test_invalid_account_ids_are_rejected(value) -> None:
    with pytest.raises(IntegrationValidationError):
        normalize_ad_account_id(value)
    with pytest.raises(IntegrationValidationError):
        ad_account_path(value)


@pytest.mark.parametrize(
    "payload", [{}, {"data": {}}, {"data": ["unexpected"]}, {"data": [], "paging": []}]
)
async def test_malformed_page_fails_closed(payload) -> None:
    def handler(request):
        return httpx2.Response(200, json=payload, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        with pytest.raises(IntegrationValidationError):
            await MetaAdsClient(static_token, client=http).graph_get_paged(
                "me/adaccounts", operation="accounts", policy=READ
            )


async def test_redirect_does_not_forward_bearer() -> None:
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(302, headers={"Location": "https://example.com/"}, request=request)

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler), follow_redirects=True
    ) as http:
        with pytest.raises(IntegrationValidationError):
            await MetaAdsClient(static_token, client=http).graph_get(
                "me", operation="identity", policy=READ
            )
    assert len(requests) == 1


@pytest.mark.parametrize("edge", ["permissions", "adaccounts"])
async def test_canonical_system_user_pagination_rebuilds_original_path(edge) -> None:
    requests = []

    def handler(request):
        requests.append(request)
        payload = {"data": [{"id": str(len(requests))}]}
        if len(requests) == 1:
            payload["paging"] = {
                "next": f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/700/{edge}"
                "?after=cursor-2&access_token=foreign&appsecret_proof=foreign-proof"
            }
        return httpx2.Response(200, json=payload, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        rows, truncated = await MetaAdsClient(static_token, client=http).graph_get_paged(
            f"me/{edge}", operation="discover", policy=READ, params={"limit": 100}
        )
    assert rows == [{"id": "1"}, {"id": "2"}]
    assert truncated is False
    assert [request.url.path for request in requests] == [
        f"/{META_GRAPH_API_VERSION}/me/{edge}"
    ] * 2
    assert dict(requests[1].url.params) == {"limit": "100", "after": "cursor-2"}
    assert all(request.headers["Authorization"] == f"Bearer {TOKEN}" for request in requests)


@pytest.mark.parametrize("code", [4, 1])
@pytest.mark.parametrize("trace_content", ["reference", "token", "proof", "secret"])
async def test_exhausted_retries_keep_safe_trace_without_request_secrets(
    monkeypatch, caplog, code, trace_content
) -> None:
    secret = "test-meta-app-secret"
    proof = hmac.new(secret.encode(), TOKEN.encode(), hashlib.sha256).hexdigest()
    trace = {"reference": "trace-final", "token": TOKEN, "proof": proof, "secret": secret}[
        trace_content
    ]
    monkeypatch.setattr(settings, "INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS", 2)
    monkeypatch.setattr("services.integrations.http.asyncio.sleep", AsyncMock())
    caplog.set_level(logging.DEBUG)

    def handler(request):
        return httpx2.Response(
            400,
            json={"error": {"code": code, "fbtrace_id": trace, "message": TOKEN}},
            request=request,
        )

    expected = IntegrationRateLimitError if code == 4 else IntegrationConnectionError
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        with pytest.raises(expected) as failure:
            await MetaAdsClient(static_token, app_secret=SecretStr(secret), client=http).graph_get(
                "me", operation="identity", policy=READ
            )
    assert ("trace-final" if trace_content == "reference" else "[redacted]") in str(failure.value)
    assert failure.value.original_error is None
    for sensitive in (TOKEN, secret, proof):
        assert sensitive not in str(failure.value)
        assert sensitive not in failure.value.user_message
        assert sensitive not in caplog.text
